"""Recoverable character-list visibility; never deletes a job, file or budget row.

Service listing remains complete because it also supplies paid daily exposure and
request recovery. Presentation consumers decide which flagged rows to display.
"""
from __future__ import annotations

import json
import re

from sqlalchemy import select

from newsflow.db.models import AppSetting
from .schema import CharacterError

PREFIX = 'char-visibility:'  # 16+32 characters, within AppSetting's 50-character key.
IDENTIFIER = re.compile(r'[a-f0-9]{32}\Z')
PROCESSING = frozenset({'writing', 'preparing', 'generating', 'retry_quoting', 'composing'})
DEFAULTS = {'v': 1, 'history': False, 'recent': False}


def _decode(raw):
    value=json.loads(raw)
    if (not isinstance(value,dict) or set(value)!=set(DEFAULTS)
            or type(value['v']) is not int or value['v']!=1
            or any(type(value[k]) is not bool for k in ('history','recent'))):
        raise ValueError('invalid-character-visibility')
    return value


def read_visibility(sessions):
    result={}
    with sessions() as session:
        for row in session.scalars(select(AppSetting).where(AppSetting.key.like(PREFIX+'%'))):
            identifier=row.key.removeprefix(PREFIX)
            if not IDENTIFIER.fullmatch(identifier):
                continue
            try:
                value=_decode(row.value)
            except (ValueError,TypeError):
                # A damaged preference must not conceal a potentially billable job.
                continue
            result[identifier]={'trashed':value['history'],'recentHidden':value['recent']}
    return result


def set_visibility(service, identifier, scope, hidden):
    if (not isinstance(identifier,str) or not IDENTIFIER.fullmatch(identifier)
            or not isinstance(scope,str) or scope not in {'history','recent'} or type(hidden) is not bool):
        raise ValueError('invalid-character-visibility-input')

    def apply():
        job=service.read(identifier)
        if scope=='history' and hidden and job['state'] in PROCESSING:
            raise CharacterError('busy')
        with service.sessions.begin() as session:
            # Serialize metadata changes from separate browser tabs. This does
            # not alter the job's own journal, reservations, approvals or state.
            session.connection().exec_driver_sql('BEGIN IMMEDIATE')
            key=PREFIX+identifier
            row=session.get(AppSetting,key)
            value=_decode(row.value) if row is not None else dict(DEFAULTS)
            value[scope]=hidden
            text=json.dumps(value,separators=(',',':'))
            if row is None:
                session.add(AppSetting(key=key,value=text))
            else:
                row.value=text
        unknown=(job['state'] in {'submission_unknown','status_or_download_failed'}
                 or (job['state']=='script_failed' and job.get('response_received') is not True)
                 or any(scene.get('state')=='unknown' for scene in job.get('scenes',[])))
        result={'id':identifier,'scope':scope,'hidden':hidden,'trashed':value['history'],
                'recentHidden':value['recent'],'recoverable':True}
        if unknown and hidden:
            result['warning']='결과 불명 작업을 목록에서 숨깁니다. 원본·비용 기록은 유지되며 자동 재실행하지 않습니다.'
        return result

    if scope=='history' and hidden:
        # The same service lock protects transition-to-generating/composing, so
        # trash cannot race a paid submission or local composition start.
        with service.lock():
            return apply()
    # Recent-list preferences and restoring visibility do not stop/rewrite jobs.
    return apply()
