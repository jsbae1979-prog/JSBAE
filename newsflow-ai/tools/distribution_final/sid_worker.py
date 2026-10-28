"""Real-SID disposable CI probe; no production app, keys, scheduler or publishing."""
import argparse,asyncio,hashlib,http.client,json,os,sqlite3,sys,threading,time
from pathlib import Path

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,required=True);args=ap.parse_args()
    if os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('RUNNER_OS')!='Windows' or sys.version_info[:3]!=(3,14,7):
        raise RuntimeError('Real disposable Windows CI only; do not forge CI flags')
    context=json.loads(args.input.read_text(encoding='utf8'))
    common=Path(context['root']).resolve();runner=Path(os.environ['RUNNER_TEMP']).resolve()
    if not common.is_relative_to(runner) or common==runner or not (common/'owned-real-sid.json').is_file():raise RuntimeError('Owned Runner TEMP root required')
    sys.path.insert(0,str(common/'code/src'))
    import win32security,win32crypt
    from newsflow.distribution.windows_profile import current_sid,private_directory,distribution_profile,reserve_user_socket
    from newsflow.distribution.local_access import LaunchSession,LocalAccess
    from newsflow.samples.catalog import Samples,PREFIX
    from newsflow.db.models import AppSetting
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import uvicorn
    sid=win32security.ConvertSidToStringSid(current_sid())
    if sid!=context['expected_sid']:raise RuntimeError('Wrong Windows logon identity')
    admin=win32security.CheckTokenMembership(None,win32security.ConvertStringSidToSid('S-1-5-32-544'))
    if admin:raise RuntimeError('Probe requires standard user')
    alias=context['alias'];base=private_directory(common/('profile-'+alias));data=distribution_profile(base)
    engine=create_engine('sqlite:///'+str(data/'state.db'));AppSetting.__table__.create(engine)
    sessions=sessionmaker(engine,expire_on_commit=False);catalog=Samples(sessions,data,None)
    sample='character-robot' if alias=='A' else 'character-cat'
    other='character-cat' if alias=='A' else 'character-robot'
    original=catalog.states()
    catalog.hide(sample,True);catalog.copy(sample);catalog.copy(sample)
    states=catalog.states()
    assert states[PREFIX+'hidden:'+sample]=='true'
    assert PREFIX+'hidden:'+other not in original and PREFIX+'copy:'+other not in original
    assert len(list((data/'sample-copies/v1'/sample).iterdir()))==1
    plaintext=b'SYNTHETIC-REAL-SID-'+alias.encode()
    cipher=win32crypt.CryptProtectData(plaintext,None,None,None,None,1)
    (data/'synthetic.dpapi').write_bytes(cipher)
    assert win32crypt.CryptUnprotectData(cipher,None,None,None,1)[1]==plaintext
    result={'alias':alias,'actual_sid_matches_created_account':True,'sid_fingerprint':hashlib.sha256(sid.encode()).hexdigest(),
            'standard_user':not admin,'own_dpapi_roundtrip':True,'own_sample_hide_and_copy':True,'repeated_copy_count':1,
            'other_sample_initially_unmodified':True,'paid_calls':0,'sns_calls':0,'full_product_app_started':False}
    listener=reserve_user_socket();port=listener.getsockname()[1];session=LaunchSession(port)
    async def endpoint(scope,receive,send):
        payload=json.dumps({'alias':alias,'state':'synthetic'}).encode()
        await send({'type':'http.response.start','status':200,'headers':[(b'content-type',b'application/json')]})
        await send({'type':'http.response.body','body':payload})
    server=uvicorn.Server(uvicorn.Config(LocalAccess(endpoint,session),host='127.0.0.1',port=port,
        lifespan='off',log_level='error',access_log=False,loop='newsflow.runtime:windows_server_loop'))
    thread=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True);thread.start()
    def request(target,path,method='GET',headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',target,timeout=5)
        try:
            connection.request(method,path,headers=headers or {});response=connection.getresponse();body=response.read(4096)
            return response.status,dict(response.getheaders()),body
        finally:connection.close()
    try:
        deadline=time.monotonic()+15
        while not server.started and thread.is_alive() and time.monotonic()<deadline:time.sleep(.05)
        if not server.started:raise RuntimeError('Synthetic gate did not start')
        bootstrap=session.launch_url().split('#')[1]
        code,headers,_=request(port,'/__local/claim','POST',{'Origin':session.origin,'X-NewsFlow-Bootstrap':bootstrap,'Content-Length':'0'})
        assert code==204
        cookie=next(v for k,v in headers.items() if k.lower()=='set-cookie').split(';')[0]
        assert request(port,'/api/private',headers={'Cookie':cookie})[0]==200
        result.update(port=port,own_authenticated_http=True)
        if alias=='A':
            (data/'ready.json').write_text(json.dumps({'port':port,'db':str(data/'state.db'),'copy':str(catalog.copy_path(catalog.get(sample))),'cipher':str(data/'synthetic.dpapi')}),encoding='utf8')
            deadline=time.monotonic()+120
            while not (data/'stop').exists() and time.monotonic()<deadline:time.sleep(.1)
            if not (data/'stop').exists():raise RuntimeError('Coordinator stop deadline')
            after=catalog.states();result['peer_did_not_change_own_sample_state']=after==states
            assert result['peer_did_not_change_own_sample_state']
        else:
            peer=context['peer']
            assert peer['port']!=port
            for name,path in [('peer_database_file_denied',peer['db']),('peer_sample_copy_denied',peer['copy'])]:
                try:Path(path).read_bytes()
                except PermissionError:result[name]=True
                else:raise RuntimeError('Other user private file was readable')
            try:
                db=sqlite3.connect(Path(peer['db']).as_uri()+'?mode=ro',uri=True)
                try:db.execute('select count(*) from sqlite_master').fetchone()
                finally:db.close()
            except sqlite3.OperationalError as exc:
                if getattr(exc,'sqlite_errorcode',None) not in {3,8,23}:raise
                result['peer_sqlite_open_denied']=True
            else:raise RuntimeError('Other user database opened')
            exported=(common/'cipher-A-for-negative-test.bin').read_bytes()
            try:win32crypt.CryptUnprotectData(exported,None,None,None,1)
            except Exception:result['peer_dpapi_decryption_denied']=True
            else:raise RuntimeError('Other SID decrypted CurrentUser DPAPI')
            result['peer_anonymous_api_denied']=request(peer['port'],'/api/private')[0]==403
            forged=f'nf_local_{peer["port"]}='+session._session
            result['peer_foreign_session_denied']=request(peer['port'],'/api/private',headers={'Cookie':forged})[0]==403
            result['simultaneous_distinct_ports']=True
            assert result['peer_anonymous_api_denied'] and result['peer_foreign_session_denied']
    finally:
        server.should_exit=True;thread.join(timeout=10);listener.close();engine.dispose()
    result['owned_server_exited']=not thread.is_alive()
    assert result['owned_server_exited']
    (data/'result.json').write_text(json.dumps(result,indent=2),encoding='utf8')

if __name__=='__main__':main()
