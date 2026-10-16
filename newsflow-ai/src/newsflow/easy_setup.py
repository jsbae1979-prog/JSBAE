"""Local readiness diagnostics and transactional first-run preferences; never calls an API."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

from PIL import ImageFont
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .db.models import AppSetting
from .python_policy import PYTHON_GUIDANCE, supported
from .video.engine import FFmpegAdapter, RenderError, font_path
from .video.tts import SpeechSettings, TTSError, TTSPolicyError, WindowsTTS

STEPS = ['시작 안내', '뉴스 수집 방식', 'AI 기능', '영상 제작', '음성과 자막', '저장 위치', '완료와 테스트']
DEFAULTS = {'source': 'sample', 'ai': 'offline', 'duration': '30', 'platform': 'youtube',
            'voice': 'offline-silence', 'font_size': '48', 'subtitle_y': '1420',
            'rate': '0', 'pause_ms': '250'}
RATE_CHOICES = {'-3': '느리게', '-2': '조금 느리게', '-1': '약간 느리게', '0': '보통', '1': '약간 빠르게', '2': '조금 빠르게', '3': '빠르게'}
PAUSE_CHOICES = {'0': '쉼 없음', '150': '짧게', '250': '보통', '400': '여유 있게', '600': '길게'}
# One install sentence for every screen and the readiness check (voices page, wizard step 5, diagnostics).
VOICE_INSTALL_GUIDE = ('Windows 설정 → 시간 및 언어 → 언어 및 지역 → 한국어 → 언어 옵션에서 음성(텍스트 음성 변환)을 '
                       '설치한 뒤 NewsFlow를 종료하고 run.bat를 다시 실행하세요.')
POLICY_GUIDE = ('PowerShell 스크립트 실행 정책 때문에 Windows 음성 기능을 사용할 수 없습니다. PowerShell에서 '
                'Get-ExecutionPolicy -List로 현재 정책을 확인하세요. 사용자의 결정으로 '
                'Set-ExecutionPolicy -Scope CurrentUser RemoteSigned를 적용할 수 있지만 이 앱은 정책을 바꾸지 않습니다. '
                '바꾸지 않으려면 무음 검토영상으로 제작하세요.')
# Human listening record (docs/korean_tts_listening_checklist.md). Only a person fills it in; nothing
# in the app or CI derives a verdict, and "pass" is rejected while any item is marked inaccurate.
LISTENING_ITEMS = {'clarity': '명료도·음량·잡음·끝 잘림', 'numbers': '숫자 (연도·큰 수·소수·단위)',
                   'dates': '날짜·시간', 'english': '영문 (글자 읽기·발음형·영단어)', 'pauses': '문장 사이 쉼',
                   'speed': '속도', 'length': '길이 (실제 vs 화면 예상 ±30%)', 'subtitle_sync': '자막 동기 (±0.5초)'}
LISTENING_VALUES = {'ok': '정확', 'bad': '부정확', 'unknown': '불명'}
LISTENING_VERDICTS = {'pass': 'PASS', 'fail': 'FAIL', 'not_verified': 'NOT VERIFIED'}
LISTENING_KEY = 'voice_listening_last'
SUMMARY_SEPARATOR = ' · '
MAX_LISTENING_FILES = 50
PREVIEW_NAME = re.compile(r'preview-[0-9a-f]{32}\.wav')
LISTENING_NAME = re.compile(r'listening-[0-9a-f]{32}\.json')
_CONTROL = re.compile(r'[\x00-\x1f\x7f]')
_CONTROL_IN_NOTES = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


class SetupError(Exception):
    pass


def voice_catalog() -> list[dict[str, str]]:
    if sys.platform != 'win32':
        return []
    return WindowsTTS().voice_details()


def diagnostics(data_dir: Path, sessions: sessionmaker[Session]) -> dict[str, Any]:
    """Only fixed local tools; raw exceptions, paths from tools, and secrets never enter results."""
    checks: list[dict[str, str | bool]] = []

    def add(key: str, label: str, ok: bool, guidance: str, required: bool = True) -> None:
        checks.append({'key': key, 'label': label, 'status': 'pass' if ok else 'needs_attention',
                       'guidance': '준비되었습니다.' if ok else guidance, 'required': required})

    add('python', 'Python 실행 환경', supported(), PYTHON_GUIDANCE)
    try:
        FFmpegAdapter().check()
        media = True
    except (RenderError, OSError):
        media = False
    add('media', '영상 제작 도구 (FFmpeg · ffprobe)', media,
        '시작 안내의 FFmpeg 설치 방법을 따라 두 실행 파일을 PATH에 추가한 뒤 프로그램을 다시 실행하세요.')
    try:
        font = ImageFont.truetype(str(font_path()), 48)
        masks = [bytes(font.getmask(s)) for s in ('가', '나', '\U0010ffff')]
        korean_font = all(masks) and len(set(masks)) == 3
    except (RenderError, OSError, ValueError):
        korean_font = False
    add('font', '한국어 글꼴', korean_font, 'Windows 언어 설정에서 한국어 글꼴을 설치하거나 고급 안내에 따라 글꼴 경로를 지정하세요.')
    try:
        with TemporaryDirectory(prefix='설정 확인 ', dir=data_dir) as directory:
            p = Path(directory) / '한글 파일.txt'
            p.write_text('저장 확인', encoding='utf-8')
            writable = p.read_text(encoding='utf-8') == '저장 확인'
    except (OSError, ValueError):
        writable = False
    try:
        with sessions() as session:
            # Exercise database writes without changing a setting or committing a probe row.
            # A readable but read-only DB must not be reported as ready.
            session.execute(text("UPDATE app_settings SET value=value WHERE key='request_timeout'"))
            session.rollback()
            db_ok = True
    except SQLAlchemyError:
        db_ok = False
    try:
        disk_ok = shutil.disk_usage(data_dir).free >= 600 * 1024 * 1024
    except OSError:
        disk_ok = False
    add('storage', '저장 폴더와 데이터베이스', writable and db_ok, '저장 폴더 쓰기 권한과 디스크 상태를 확인하세요. 기존 데이터는 삭제하지 마세요.')
    add('space', '영상 제작 여유 공간', disk_ok, '저장 드라이브에 최소 600MB의 여유 공간을 확보하세요.')
    try:
        voices = voice_catalog()
        korean = [v for v in voices if v['culture'].lower().startswith('ko-')]
        voice_state = 'available' if korean else 'not_installed'
    except TTSPolicyError:
        voices, korean, voice_state = [], [], 'blocked_policy'
    except TTSError:
        voices, korean, voice_state = [], [], 'unavailable'
    add('korean_voice', '한국어 Windows 음성 (선택)', bool(korean),
        POLICY_GUIDE if voice_state == 'blocked_policy'
        else VOICE_INSTALL_GUIDE + ' 이 앱이 사용하는 SAPI 음성이 보여야 선택할 수 있습니다. 무음으로도 제작할 수 있어요.',
        False)
    try:
        listening = listening_summary(sessions)
    except SQLAlchemyError:
        listening = None
    quality = ('사람의 청취·시청 평가는 아직 하지 않았습니다.' if listening is None
               else f"사람 청취 결과: {listening['label']} ({listening['date']}, {listening['listener']})")
    return {'ready': all(c['status'] == 'pass' for c in checks if c['required']), 'checks': checks,
            'voices': voices, 'korean_voice': voice_state, 'external_calls': 0, 'quality': quality}


def initial_state(session: Session) -> dict[str, Any]:
    # Existing installations keep their defaults when opening the wizard for the first time.
    values = dict(DEFAULTS)
    allowed = {'source': {'sample', 'feeds'}, 'duration': {'30', '45', '60'},
               'platform': {'youtube', 'instagram'}, 'font_size': {'40', '48', '56'},
               'subtitle_y': {'1280', '1420'}, 'rate': set(RATE_CHOICES), 'pause_ms': set(PAUSE_CHOICES)}
    for key, choices in allowed.items():
        prefix = 'autopilot_' if key in {'source', 'duration', 'platform'} else 'video_default_'
        row = session.get(AppSetting, prefix + key)
        if row and row.value in choices:
            values[key] = row.value
    row = session.get(AppSetting, 'video_default_voice')
    if row and 0 < len(row.value) <= 200:
        values['voice'] = row.value
    return {'revision': 0, 'step': 1, 'completed': False, 'values': values}


def read_state(sessions: sessionmaker[Session]) -> dict[str, Any]:
    with sessions() as session:
        row = session.get(AppSetting, 'easy_setup')
        return json.loads(row.value) if row else initial_state(session)


def save_step(sessions: sessionmaker[Session], step: int, revision: int, values: dict[str, str]) -> None:
    if step == 2 and values.get('source') not in {'sample', 'feeds'}:
        raise SetupError('뉴스 수집 방식을 선택하세요.')
    if step == 3 and values.get('ai') != 'offline':
        raise SetupError('이 마법사에서는 외부 API 없는 기본 대본만 사용할 수 있습니다.')
    if step == 4 and (values.get('duration') not in {'30', '45', '60'} or values.get('platform') not in {'youtube', 'instagram'}):
        raise SetupError('영상 길이와 목적지를 선택하세요.')
    if step == 5:
        if values.get('font_size') not in {'40', '48', '56'} or values.get('subtitle_y') not in {'1280', '1420'}:
            raise SetupError('제공된 자막 크기와 위치를 선택하세요.')
        values.setdefault('rate', DEFAULTS['rate'])
        values.setdefault('pause_ms', DEFAULTS['pause_ms'])
        if values['rate'] not in RATE_CHOICES or values['pause_ms'] not in PAUSE_CHOICES:
            raise SetupError('제공된 발화 속도와 문장 쉼을 선택하세요.')
        if values.get('voice') != 'offline-silence':
            try:
                valid = values.get('voice') in [v['name'] for v in voice_catalog() if v['culture'].lower().startswith('ko-')]
            except TTSError:
                valid = False
            if not valid:
                raise SetupError('사용 가능한 한국어 음성을 선택하거나 무음을 선택하세요.')
    if step == 6 and values.get('storage_confirmed') != 'yes':
        raise SetupError('저장 위치를 확인해 주세요.')
    fields = {1: set(), 2: {'source'}, 3: {'ai'}, 4: {'duration', 'platform'},
              5: {'voice', 'font_size', 'subtitle_y', 'rate', 'pause_ms'}, 6: set(), 7: set()}
    if step not in fields or set(values) - fields[step] - {'storage_confirmed'}:
        raise SetupError('설정 항목을 확인하세요.')
    with sessions.begin() as session:
        session.connection().exec_driver_sql('BEGIN IMMEDIATE')
        row = session.get(AppSetting, 'easy_setup')
        state = json.loads(row.value) if row else initial_state(session)
        if state['revision'] != revision or step > state['step']:
            raise SetupError('다른 창에서 설정이 바뀌었거나 이전 단계가 남았습니다. 새로고침해 주세요.')
        state['values'].update({key: values[key] for key in fields[step]})
        state.update(revision=revision + 1, step=min(7, step + 1), completed=step == 7)
        if step == 7:
            for key, value in state['values'].items():
                name = 'autopilot_' + key if key in {'source', 'duration', 'platform'} else 'video_default_' + key
                existing = session.get(AppSetting, name)
                if existing:
                    existing.value = value
                else:
                    session.add(AppSetting(key=name, value=value))
        payload = json.dumps(state, ensure_ascii=False)
        if row:
            row.value = payload
        else:
            session.add(AppSetting(key='easy_setup', value=payload))


def preview_preferences(sessions: sessionmaker[Session]) -> tuple[str, int, int]:
    with sessions() as session:
        def value(key: str) -> str:
            row = session.get(AppSetting, 'video_default_' + key)
            return row.value if row else DEFAULTS[key]
        voice, size, position = value('voice'), value('font_size'), value('subtitle_y')
        if size not in {'40', '48', '56'} or position not in {'1280', '1420'} or len(voice) > 200:
            raise SetupError('음성과 자막 설정을 다시 저장하세요.')
        return voice, int(size), int(position)


def speech_preferences(sessions: sessionmaker[Session]) -> SpeechSettings:
    """Saved narration rate/pause; unknown or missing values fall back to the defaults."""
    with sessions() as session:
        def value(key: str) -> str:
            row = session.get(AppSetting, 'video_default_' + key)
            return row.value if row and row.value in (RATE_CHOICES if key == 'rate' else PAUSE_CHOICES) else DEFAULTS[key]
        return SpeechSettings(int(value('rate')), int(value('pause_ms')))


def save_voice_preferences(sessions: sessionmaker[Session], voice: str, rate: str, pause_ms: str) -> None:
    """Explicit voice page save; the voice must be the silent option or an installed Korean SAPI voice."""
    if rate not in RATE_CHOICES or pause_ms not in PAUSE_CHOICES:
        raise SetupError('제공된 발화 속도와 문장 쉼을 선택하세요.')
    if voice != 'offline-silence':
        try:
            valid = voice in [v['name'] for v in voice_catalog() if v['culture'].lower().startswith('ko-')]
        except TTSError:
            valid = False
        if not valid:
            raise SetupError('사용 가능한 한국어 음성을 선택하거나 무음을 선택하세요.')
    with sessions.begin() as session:
        for key, value in (('voice', voice), ('rate', rate), ('pause_ms', pause_ms)):
            row = session.get(AppSetting, 'video_default_' + key)
            if row:
                row.value = value
            else:
                session.add(AppSetting(key='video_default_' + key, value=value))


def listening_summary(sessions: sessionmaker[Session]) -> dict[str, str] | None:
    """Latest human listening record summary from AppSetting, or None when nobody has listened yet."""
    with sessions() as session:
        row = session.get(AppSetting, LISTENING_KEY)
        value = row.value if row else ''
    parts = value.split(SUMMARY_SEPARATOR, 3)
    if len(parts) < 3 or parts[0] not in LISTENING_VERDICTS:
        return None
    return {'verdict': parts[0], 'label': LISTENING_VERDICTS[parts[0]], 'date': parts[1],
            'listener': parts[2], 'voice': parts[3] if len(parts) > 3 else ''}


def record_listening(data_dir: Path, sessions: sessionmaker[Session], values: dict[str, str]) -> dict[str, Any]:
    """Store what a human listener decided; the app validates the form but never derives the verdict.

    The record is a JSON file under ``voice-listening/`` (at most MAX_LISTENING_FILES kept) plus a
    short AppSetting summary. No migration: nothing else in the database changes.
    """
    listener = str(values.get('listener', '')).strip()
    if not 1 <= len(listener) <= 40 or _CONTROL.search(listener) or SUMMARY_SEPARATOR.strip() in listener:
        raise SetupError('청취자 이름을 1~40자로 입력하세요. 가운뎃점(·)은 쓸 수 없습니다.')
    voice = str(values.get('voice', '')).strip()
    if len(voice) > 200 or _CONTROL.search(voice) or SUMMARY_SEPARATOR.strip() in voice:
        raise SetupError('음성 이름을 확인하세요.')
    rate, pause_ms = str(values.get('rate', '')), str(values.get('pause_ms', ''))
    if rate not in RATE_CHOICES or pause_ms not in PAUSE_CHOICES:
        raise SetupError('제공된 발화 속도와 문장 쉼을 선택하세요.')
    preview = str(values.get('preview', '')).strip()
    if preview and not PREVIEW_NAME.fullmatch(preview):
        raise SetupError('미리 듣기 파일 이름을 확인하세요.')
    items: dict[str, str] = {}
    for key in LISTENING_ITEMS:
        value = str(values.get(key, ''))
        if value not in LISTENING_VALUES:
            raise SetupError('모든 청취 항목을 정확·부정확·불명 중에서 선택하세요.')
        items[key] = value
    verdict = str(values.get('verdict', ''))
    if verdict not in LISTENING_VERDICTS:
        raise SetupError('종합 판정을 PASS·FAIL·NOT VERIFIED 중에서 선택하세요.')
    if verdict == 'pass' and any(value != 'ok' for value in items.values()):
        # docs/korean_tts_listening_checklist.md: PASS means every item was heard and judged 정확.
        raise SetupError('PASS는 모든 항목이 정확일 때만 기록할 수 있습니다. 부정확·불명 항목이 있으면 FAIL 또는 NOT VERIFIED를 선택하세요.')
    notes = str(values.get('notes', '')).strip()
    if len(notes) > 500 or _CONTROL_IN_NOTES.search(notes):
        raise SetupError('메모는 500자 이하로 입력하세요.')
    preview_sha256 = ''
    if preview:
        source = data_dir / 'voice-preview' / preview
        if source.is_file() and not source.is_symlink():
            preview_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    created_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    record: dict[str, Any] = {
        'schema': 'voice-listening/1', 'created_at': created_at, 'listener': listener, 'voice': voice,
        'rate': int(rate), 'pause_ms': int(pause_ms), 'preview': preview, 'preview_sha256': preview_sha256,
        'items': items, 'verdict': verdict, 'notes': notes, 'recorded_by': 'human',
    }
    directory = data_dir / 'voice-listening'
    directory.mkdir(parents=True, exist_ok=True)
    name = f'listening-{uuid4().hex}.json'
    (directory / name).write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding='utf-8')
    kept = sorted((p for p in directory.iterdir() if LISTENING_NAME.fullmatch(p.name) and p.is_file()
                   and not p.is_symlink()), key=lambda p: (p.stat().st_mtime, p.name))
    for old in kept[:max(0, len(kept) - MAX_LISTENING_FILES)]:
        old.unlink(missing_ok=True)
    summary = SUMMARY_SEPARATOR.join((verdict, created_at[:10], listener, voice))[:200]
    with sessions.begin() as session:
        row = session.get(AppSetting, LISTENING_KEY)
        if row:
            row.value = summary
        else:
            session.add(AppSetting(key=LISTENING_KEY, value=summary))
    return {**record, 'file': name, 'summary': summary}


def main() -> int:
    from filelock import FileLock

    from .config import Settings
    from .db.session import make_engine, migrate, session_factory
    from .paths import prepare_data_dir
    try:
        settings = Settings.from_env()
        prepare_data_dir(settings.data_dir)
        (settings.data_dir / "outputs" / "videos").mkdir(parents=True, exist_ok=True)
        # Never migrate a database while another app process is using it.
        with FileLock(str(settings.data_dir / 'migration.lock')).acquire(timeout=0):
            engine = make_engine(settings.data_dir / 'newsflow.db')
            try:
                migrate(engine)
                result = diagnostics(settings.data_dir, session_factory(engine))
                for check in result['checks']:
                    print(f"{check['label']}: {check['status']} · {check['guidance']}")
                print('점검을 마쳤습니다. run.bat 실행 후 처음 설정하기를 열어 주세요.')
                return 0 if result['ready'] else 1
            finally:
                engine.dispose()
    except Exception:  # noqa: BLE001 -- do not print connection strings, secrets or raw OS errors
        print('준비 점검을 완료하지 못했습니다. 실행 중인 NewsFlow를 닫고 저장 폴더 권한을 확인하세요. 기존 데이터는 삭제하지 마세요.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
