"""Only approved disposable Windows Actions full-app procedure."""
from test_full_app_forms import client

def test_core_context_get_is_readonly_and_keeps_auth_csp_boundary(client):
    c,app=client
    from sqlalchemy import select
    from newsflow.db.models import AppSetting
    with app.state.sessions() as s:
        before=[(r.key,r.value) for r in s.scalars(select(AppSetting))]
    first=c.get('/api/studio/production-context')
    second=c.get('/api/studio/production-context')
    assert first.status_code==second.status_code==200
    assert first.json()==second.json()
    assert first.json()['schemaVersion']==1 and first.json()['top3']==[]
    assert first.json()['blockedReason']
    with app.state.sessions() as s:
        assert before==[(r.key,r.value) for r in s.scalars(select(AppSetting))]
    foreign=c.get('/api/studio/production-context',headers={'Host':'untrusted.invalid'})
    assert foreign.status_code in {400,403}
    shell=c.get('/studio/shorts')
    assert shell.status_code==200 and 'unsafe-inline' not in shell.headers['Content-Security-Policy']
