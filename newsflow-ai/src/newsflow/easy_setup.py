"""Local readiness diagnostics and transactional first-run preferences; never calls an API."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from PIL import ImageFont
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .db.models import AppSetting
from .video.engine import FFmpegAdapter, RenderError, font_path
from .video.tts import TTSError, WindowsTTS

STEPS = ['시작 안내', '뉴스 수집 방식', 'AI 기능', '영상 제작', '음성과 자막', '저장 위치', '완료와 테스트']
DEFAULTS = {'source': 'sample', 'ai': 'offline', 'duration': '30', 'platform': 'youtube',
            'voice': 'offline-silence', 'font_size': '48', 'subtitle_y': '1420'}


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

    add('python', 'Python 실행 환경', sys.version_info[:2] == (3, 12), 'Python 3.12를 설치한 뒤 run.bat를 다시 실행하세요.')
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
    except TTSError:
        voices, korean, voice_state = [], [], 'unavailable'
    add('korean_voice', '한국어 Windows 음성 (선택)', bool(korean),
        '설정 → 시간 및 언어 → 언어 및 지역 → 한국어 언어 옵션에서 음성 기능을 설치하세요. 이 앱이 사용하는 SAPI 음성이 보여야 선택할 수 있습니다. 무음으로도 제작할 수 있어요.', False)
    return {'ready': all(c['status'] == 'pass' for c in checks if c['required']), 'checks': checks,
            'voices': voices, 'korean_voice': voice_state, 'external_calls': 0,
            'quality': '사람의 청취·시청 평가는 아직 하지 않았습니다.'}


def initial_state(session: Session) -> dict[str, Any]:
    # Existing installations keep their defaults when opening the wizard for the first time.
    values = dict(DEFAULTS)
    allowed = {'source': {'sample', 'feeds'}, 'duration': {'30', '45', '60'},
               'platform': {'youtube', 'instagram'}, 'font_size': {'40', '48', '56'},
               'subtitle_y': {'1280', '1420'}}
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
              5: {'voice', 'font_size', 'subtitle_y'}, 6: set(), 7: set()}
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
