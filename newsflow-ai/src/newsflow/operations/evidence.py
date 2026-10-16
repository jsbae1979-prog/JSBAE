"""Allowlisted local human attestations, separate from automated checks and voice quality."""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from newsflow.db.models import AppSetting
from newsflow.easy_setup import SetupError

KEY = 'windows_operations_review_v1'
ITEMS = {'launch':'run.bat 실행·중복 실행·포트 안내', 'schedule':'예약 활성화·다음 실행 시각',
    'news':'공개 뉴스 수집·원문 검토', 'video30':'30초 영상 재생·음성·자막',
    'video45':'45초 영상 재생·음성·자막', 'video60':'60초 영상 재생·음성·자막',
    'restart':'앱 재시작 후 데이터·영상 보존', 'reboot':'PC 재부팅·로그인 후 동작',
    'sleep':'절전 복귀·지난 예약 건너뛰기', 'startup':'동의 후 자동 시작 등록·해제'}
VERDICTS = ('NOT VERIFIED','PASS','FAIL')


def read(sessions: sessionmaker[Session]) -> dict:
    with sessions() as session:
        row = session.get(AppSetting,KEY)
        if row:
            return json.loads(row.value)
    return {'revision':0,'items':dict.fromkeys(ITEMS,'NOT VERIFIED'),'at':None,
            'source':'not_reviewed','host':'not_recorded'}


def save(sessions: sessionmaker[Session], revision: int, values: dict[str,str], consent: bool) -> None:
    if not consent or set(values) != set(ITEMS) or any(v not in VERDICTS for v in values.values()):
        raise SetupError('직접 확인한 항목만 판정하고 확인 기록에 동의하세요.')
    with sessions.begin() as session:
        session.connection().exec_driver_sql('BEGIN IMMEDIATE')
        row = session.get(AppSetting,KEY)
        current = json.loads(row.value)['revision'] if row else 0
        if revision != current:
            raise SetupError('다른 창에서 기록이 바뀌었습니다. 새로고침하세요.')
        value = json.dumps({'revision':revision+1,'items':values,'at':datetime.now(UTC).isoformat(),
            'source':'human_self_report','host':'windows' if sys.platform == 'win32' else 'cloud_or_test'})
        if row:
            row.value = value
        else:
            session.add(AppSetting(key=KEY,value=value))


def export(sessions: sessionmaker[Session]) -> dict:
    review = read(sessions)
    # Deliberately excludes free text, usernames, full paths, settings, database and secrets.
    return {'schema':'newsflow-operational-review/1','human_review':review,
            'ci_result':'NOT INCLUDED','human_audio_quality':'See separate listening record; never inferred',
            'real_paid_ai_oauth_sns':'Not tested by this checklist'}
