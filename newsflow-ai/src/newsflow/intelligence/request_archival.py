"""Explicit reversible archival of a bounded batch of finished unknown API ledger entries.

Archival is not cancellation, a refund, a successful response or permission to
replay an old request. Only status changes; request identity, usage, money and
original completion timestamps remain durable and included in monthly totals.
"""
from __future__ import annotations

from collections.abc import Mapping
import json
import re
from uuid import uuid4

from sqlalchemy import select

from newsflow.db.models import APIRequestReservation, AuditLog
from .api_settings import _unknown_fingerprint

ARCHIVE_EVENT='api_unknown_archived'
RESTORE_EVENT='api_unknown_archive_restored'
ARCHIVED='archived_unknown'
COUNT=7
_ID=re.compile(r'[a-f0-9]{32}\Z')
_HASH=re.compile(r'[a-f0-9]{64}\Z')


class ArchiveError(ValueError):
    pass


def fingerprint(row):
    """Same complete-row fingerprint used by the existing API unknown review."""
    return _unknown_fingerprint(row)


def _validate(mapping,consent,expected_count):
    if (consent is not True or type(expected_count) is not int or not 1<=expected_count<=COUNT
            or not isinstance(mapping,Mapping) or len(mapping)!=expected_count
            or any(not isinstance(key,str) or not _ID.fullmatch(key)
                   or not isinstance(value,str) or not _HASH.fullmatch(value)
                   for key,value in mapping.items())):
        raise ArchiveError('명시적으로 승인한 건수(1~7개)와 결과 불명 원본 지문이 필요합니다.')
    return dict(mapping)


def _rows(session,mapping,status):
    rows=list(session.scalars(select(APIRequestReservation)
              .where(APIRequestReservation.id.in_(sorted(mapping)))
              .order_by(APIRequestReservation.id)))
    if len(rows)!=len(mapping):
        raise ArchiveError('승인한 원본 기록을 모두 찾을 수 없습니다.')
    for row in rows:
        if (row.status!=status or row.finished_at is None or fingerprint(row)!=mapping[row.id]):
            raise ArchiveError('진행 중이거나 원본 상태가 변경된 요청은 정리하지 않습니다.')
    return rows


def _audit(session,event,payload):
    message=json.dumps(payload,sort_keys=True,separators=(',',':'))
    if len(message)>500:
        raise ArchiveError('감사 기록의 제한을 초과했습니다.')
    session.add(AuditLog(level='info',event=event,message=message))


def archive_unknown(sessions,mapping,*,consent,expected_count=COUNT):
    expected=_validate(mapping,consent,expected_count)
    batch=uuid4().hex
    archived={}
    with sessions.begin() as session:
        session.connection().exec_driver_sql('BEGIN IMMEDIATE')
        rows=_rows(session,expected,'unknown')
        # Validate the entire approved batch before changing even one status.
        for row in rows:
            row.status=ARCHIVED
            archived[row.id]=fingerprint(row)
            _audit(session,ARCHIVE_EVENT,{
                'scope':'archive_finished_unknown_v1','batch_id':batch,
                'reservation_id':row.id,'before':expected[row.id],'after':archived[row.id],
                'old_status':'unknown','new_status':ARCHIVED})
    return {'batch_id':batch,'status':ARCHIVED,'ids':sorted(archived),
            'fingerprints':archived,'count':len(expected),'deleted':0,'replay_authorized':False}


def restore_unknown(sessions,mapping,*,consent,batch_id,expected_count=COUNT):
    """Separate explicit recovery only; never called by app startup or archival."""
    expected=_validate(mapping,consent,expected_count)
    if not isinstance(batch_id,str) or not _ID.fullmatch(batch_id):
        raise ArchiveError('복원할 보관 묶음을 확인하세요.')
    restored={}
    with sessions.begin() as session:
        session.connection().exec_driver_sql('BEGIN IMMEDIATE')
        rows=_rows(session,expected,ARCHIVED)
        evidence={}
        for entry in session.scalars(select(AuditLog)
                .where(AuditLog.event.in_((ARCHIVE_EVENT,RESTORE_EVENT)))):
            try:value=json.loads(entry.message)
            except (ValueError,TypeError):continue
            if not isinstance(value,dict):continue
            if entry.event==RESTORE_EVENT and value.get('restores_batch_id')==batch_id:
                raise ArchiveError('이미 복원된 보관 묶음은 재사용하지 않습니다.')
            if (entry.event==ARCHIVE_EVENT and value.get('scope')=='archive_finished_unknown_v1'
                    and value.get('batch_id')==batch_id and value.get('old_status')=='unknown'
                    and value.get('new_status')==ARCHIVED):
                evidence[value.get('reservation_id')]=value
        if set(evidence)!=set(expected) or any(evidence[key].get('after')!=value for key,value in expected.items()):
            raise ArchiveError('일치하는 원본 보관 증거가 없어 복원하지 않습니다.')
        for row in rows:
            row.status='unknown'
            restored[row.id]=fingerprint(row)
            if restored[row.id]!=evidence[row.id].get('before'):
                raise ArchiveError('원본 지문과 일치하는 상태로 복원할 수 없습니다.')
            _audit(session,RESTORE_EVENT,{
                'scope':'restore_finished_unknown_v1','restores_batch_id':batch_id,
                'reservation_id':row.id,'before':expected[row.id],'after':restored[row.id],
                'old_status':ARCHIVED,'new_status':'unknown'})
    return {'batch_id':batch_id,'status':'unknown','ids':sorted(restored),
            'fingerprints':restored,'count':len(expected),'deleted':0,'replay_authorized':False}
