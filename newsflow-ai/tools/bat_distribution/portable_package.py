"""Refresh program bytes from the accepted installation, never user data."""
import json
import shutil
from pathlib import Path
from .lifecycle import Blocked, ordinary_absolute
from .bundle_assembly import digest, program_records, create_zip
from .zip_update import FileRecord, _zip_members

CONTROLLERS = ('windows_live.py','contract_entry.py','local_work.py','operation.py','portable.py','zip_update.py')


def release(root, version, source_sha):
    text = f"""NewsFlow AI {version} — 비공개 검증용 BAT ZIP

압축을 해제한 NewsFlowAI 폴더에서 Start_NewsFlowAI.bat를 실행하세요.
별도 Python/Node.js/FFmpeg 설치나 관리자 실행은 필요하지 않습니다.
뉴스·이미지·캐릭터 제작실과 로컬 초안 저장을 제공합니다.
실제 유료 AI/OAuth/SNS/자동화 실행은 이 후보에서 차단돼 있습니다.
보안 제품 차단 시 실행을 중단하세요. 비활성화·예외 등록은 하지 마세요.

포트는 connection.json의 port에 명시합니다. 기본 예시18780이며
운영PC의18768을 강제하지 않습니다. 충돌 시 자동 변경하지 않습니다.
변경하려면 앱을 먼저 정상 종료하고 유효한1024~65535 포트를 지정하세요.
기존 운영8765는 사용하지 않습니다. 외부 LAN은 허용하지 않습니다.
connection.json은 비밀값 없는 연결 설정이며 경로/명령 입력은 불가합니다.
설정 파일의 SHA만으로 배포자 신원을 증명할 수 없습니다.

사용자 데이터: <현재 Windows 사용자 홈>/AppData/Local/NewsFlowAI-BAT/portable-v1
기존 운영v1/NewsFlowAI DB·키·미디어는 사용하거나 자동 이전하지 않습니다.
복사해 둔 다른 폴더로 임의 변경 실행하면 기존 프로필 소유권 검사로 거절됩니다.
Stop_NewsFlowAI.bat는 동일 사용자/실행파일/생성ID의 소유 프로세스만
정상 종료합니다. 다른 사용자나 기존 운영 앱은 종료하지 않습니다.
브라우저는 기본 브라우저로 열리며 일회용 인증 뒤 React로 이동합니다.

업데이트 ZIP은 서명되지 않은 비활성 검증 후보입니다.
Update_NewsFlowAI.bat는 배포자 인증서·신뢰 앵커가 없어 거절합니다.
수동 덮어쓰기나 무서명 업데이트로 검증을 우회하지 마세요.
1.0.0/1.1.0은 같은 최신 제품 bytes와 다른 릴리스 메타데이터를 사용합니다.
실제 기능 버전 간 업데이트 성공을 증명하지 않습니다.

현재 사용자 DB·키·OAuth·DPAPI·미디어·백업·세션은 포함하지 않았습니다.
권리 미확인 샘플12개도 제외했습니다. 초기 화면의 샘플 빈 상태는 정상입니다.
licenses/의 Python·의존성·FFmpeg 고지와 대응 소스 자료를 보존하세요.
라이선스와 배포자 서명 조건의 완결 또는 외부 전달 승인을 뜻하지 않습니다.
이 ZIP은 외부 사용자에게 전달하지 마세요. 검증·보존용입니다.
제품/제어 코드 SHA: {source_sha}
"""
    (root/'README.txt').write_bytes(text.replace('\n','\r\n').encode('utf-8'))
    rows=[r for r in program_records(root) if r['path'] not in {'app/layout.json','connection.json'}]
    layout={'schemaVersion':1,'pythonVersion':'3.14.7','architecture':'AMD64',
            'releaseVersion':version,'sourceSha':source_sha,'candidateOnly':True,
            'liveStartStopConnected':True,'validationOnly':False,'portableFirstRun':True,
            'updatesEnabled':False,'files':rows}
    (root/'app/layout.json').write_text(json.dumps(layout,indent=2),encoding='utf-8')


def refresh(installed, project, output, source_sha):
    installed,project,output=map(ordinary_absolute,(installed,project,output))
    if output.exists() or output.is_relative_to(installed) or installed.is_relative_to(output):
        raise Blocked('fresh-separate-output-required')
    original=json.loads((installed/'app/layout.json').read_bytes())
    output.mkdir();root=output/'staging/NewsFlowAI';root.mkdir(parents=True)
    for row in original['files']:
        from .zip_update import payload_name
        name=payload_name(row['path']);source=ordinary_absolute(installed/name)
        if not source.is_file() or source.stat().st_size!=row['bytes'] or digest(source)!=row['sha256']:
            raise Blocked('accepted-program-file-changed')
        target=root/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    for name in CONTROLLERS:
        shutil.copyfile(project/'tools/bat_distribution'/name,root/'app/controller/bat_distribution'/name)
    for name in ('Start_NewsFlowAI.bat','Stop_NewsFlowAI.bat','Update_NewsFlowAI.bat'):
        shutil.copyfile(project/'tools/bat_distribution/templates'/name,root/name)
    (root/'connection.json').write_text(json.dumps({'schemaVersion':1,'port':18780,'openBrowser':True},indent=2),encoding='utf-8')
    release(root,'1.0.0',source_sha)
    first=output/'NewsFlowAI_v1.0.0.zip';first_rows=create_zip(root,first,prefix='NewsFlowAI/')
    release(root,'1.1.0',source_sha)
    update=output/'NewsFlowAI_Update_v1.1.0.zip';update_rows=create_zip(root,update)
    _zip_members(update.read_bytes(),tuple(FileRecord(r['path'],r['bytes'],r['sha256']) for r in update_rows))
    manifest={'schemaVersion':1,'appId':'NewsFlowAI','channel':'private-bat','version':'1.1.0',
              'sequence':2,'supportedFrom':['1.0.0'],'pythonVersion':'3.14.7','architecture':'AMD64',
              'migration':'none','zipName':update.name,'zipBytes':update.stat().st_size,
              'zipSha256':digest(update),'files':update_rows}
    (output/'NewsFlowAI_Update_v1.1.0.manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    result={'sourceSha':source_sha,'runtime':'3.14.7 AMD64','updatesEnabled':False,
            'publisherSignaturePresent':False,'externalDelivery':False,'samplesIncluded':0,
            'operatingProfileIncluded':False,'productPayloadSameCode':True,
            'initial':{'file':first.name,'bytes':first.stat().st_size,'sha256':digest(first),'members':len(first_rows)},
            'update':{'file':update.name,'bytes':update.stat().st_size,'sha256':digest(update),'members':len(update_rows)}}
    (output/'PACKAGE_RESULT.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result
