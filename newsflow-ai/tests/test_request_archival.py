"""Synthetic-only archived status, exact snapshots, accounting and request identity."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
import json

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from test_api_settings import sessions

from newsflow.db.models import APIRequestReservation,AuditLog,utcnow
from newsflow.intelligence.api_settings import APIBudgetService,APISettingsError,_usage
from newsflow.intelligence.request_archival import (
    ARCHIVED,ARCHIVE_EVENT,RESTORE_EVENT,ArchiveError,archive_unknown,restore_unknown,fingerprint)


@pytest.fixture
def batch(sessions):
    now=utcnow()
    with sessions.begin() as db:
        for n in range(7):
            db.add(APIRequestReservation(id=f'{n+1:032x}',request_id=f'synthetic-unknown:{n+1}',
                provider='claude_api',kind='script',model='claude-sonnet-4-6',status='unknown',
                reserved_usd='0.20',estimated_usd='0.10' if n else None,
                bounds={'accounting':'reported_usage','search_calls':0},
                prices={'input':'3','output':'15','search':'10'},usage={'synthetic':n},test_only=True,
                created_at=now-timedelta(minutes=2),finished_at=now-timedelta(minutes=1)))
    with sessions() as db:
        rows=list(db.scalars(select(APIRequestReservation).order_by(APIRequestReservation.id)))
        return {r.id:fingerprint(r) for r in rows}


def contents(sessions):
    with sessions() as db:
        return {r.id:{c.name:deepcopy(getattr(r,c.name)) for c in r.__table__.columns}
                for r in db.scalars(select(APIRequestReservation))}


def test_archival_changes_only_status_and_preserves_all_status_monthly_accounting(sessions,batch):
    before=contents(sessions)
    with sessions() as db:usage_before=_usage(list(db.scalars(select(APIRequestReservation))),utcnow())
    result=archive_unknown(sessions,batch,consent=True)
    after=contents(sessions)
    assert result['count']==7 and result['deleted']==0 and not result['replay_authorized']
    assert set(after)==set(before)==set(batch)
    for identifier,original in before.items():
        assert after[identifier]=={**original,'status':ARCHIVED}
    with sessions() as db:
        rows=list(db.scalars(select(APIRequestReservation)))
        usage_after=_usage(rows,utcnow())
        audits=list(db.scalars(select(AuditLog).where(AuditLog.event==ARCHIVE_EVENT)))
    assert len(audits)==7 and all(len(row.message)<=500 for row in audits)
    assert {json.loads(row.message)['reservation_id'] for row in audits}==set(batch)
    for field in ('calls','held_usd','estimated_usd','reported_usd','test_calls','vendor_billing'):
        assert usage_after[field]==usage_before[field]
    assert usage_after['unknown']==0 and usage_before['unknown']==7
    assert Decimal(usage_after['held_usd'])==Decimal('1.40')


def test_one_mismatching_fingerprint_rolls_back_entire_batch_without_audit(sessions,batch):
    before=contents(sessions)
    altered={**batch,next(iter(batch)):'f'*64}
    with pytest.raises(ArchiveError):archive_unknown(sessions,altered,consent=True)
    assert contents(sessions)==before
    with sessions() as db:assert list(db.scalars(select(AuditLog)))==[]


def test_reserved_and_unfinished_unknown_are_refused_atomically(sessions,batch):
    identifier=next(iter(batch))
    for status,finished in (('reserved',utcnow()),('unknown',None)):
        with sessions.begin() as db:
            row=db.get(APIRequestReservation,identifier)
            row.status,status_before=status,row.status
            row.finished_at=finished
        before=contents(sessions)
        with sessions() as db:
            expected={row.id:fingerprint(row) for row in db.scalars(select(APIRequestReservation))}
        with pytest.raises(ArchiveError):archive_unknown(sessions,expected,consent=True)
        assert contents(sessions)==before
        with sessions() as db:assert list(db.scalars(select(AuditLog)))==[]


def test_original_request_identity_still_cannot_be_reserved_or_inserted(sessions,batch):
    archive_unknown(sessions,batch,consent=True)
    before=contents(sessions)
    original=next(iter(before.values()))
    with pytest.raises(APISettingsError,match='이미 기록된 요청'):
        APIBudgetService(sessions).reserve(provider='claude_api',request_id=original['request_id'],
            kind='script',model='claude-sonnet-4-6',max_output_tokens=3000,key_store=None)
    with pytest.raises(IntegrityError):
        with sessions.begin() as db:
            db.add(APIRequestReservation(**{**original,'id':'f'*32}))
    assert contents(sessions)==before


def test_explicit_consent_and_exactly_seven_snapshots_are_required(sessions,batch):
    before=contents(sessions)
    for mapping,consent in ((batch,False),(batch,1),(dict(list(batch.items())[:6]),True),
                            ({**batch,'bad':'f'*64},True)):
        with pytest.raises(ArchiveError):archive_unknown(sessions,mapping,consent=consent)
    assert contents(sessions)==before


def test_recovery_needs_matching_archive_evidence_and_restores_only_original_status(sessions,batch):
    before=contents(sessions)
    archived=archive_unknown(sessions,batch,consent=True)
    after=contents(sessions)
    with pytest.raises(ArchiveError):
        restore_unknown(sessions,archived['fingerprints'],consent=True,batch_id='f'*32)
    assert contents(sessions)==after
    restored=restore_unknown(sessions,archived['fingerprints'],consent=True,batch_id=archived['batch_id'])
    assert restored['fingerprints']==batch and contents(sessions)==before
    with sessions() as db:
        assert len(list(db.scalars(select(AuditLog).where(AuditLog.event==RESTORE_EVENT))))==7
    with pytest.raises(ArchiveError):
        restore_unknown(sessions,archived['fingerprints'],consent=True,batch_id=archived['batch_id'])
