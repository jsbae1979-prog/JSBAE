"""Consent-controlled, current-user Task Scheduler adapter. No task is registered on import."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from xml.etree import ElementTree as ET

from defusedxml.ElementTree import fromstring
from filelock import FileLock, Timeout


class StartupError(Exception):
    pass


# Fixed program, JSON input. No interpolated commands, shell, password, elevation or policy bypass.
SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
try {
  $p = [Console]::In.ReadToEnd() | ConvertFrom-Json
  $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
  $sid = $identity.User.Value
  $principal = New-Object Security.Principal.WindowsPrincipal($identity)
  $elevated = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  if ($p.operation -eq 'identity') { @{sid=$sid;elevated=$elevated} | ConvertTo-Json -Compress; exit 0 }
  if ($sid -ne $p.sid) { throw 'identity' }
  $s = New-Object -ComObject 'Schedule.Service'; $s.Connect(); $f = $s.GetFolder('\')
  if ($p.operation -eq 'validate') {
    $d = $s.NewTask(0); $d.XmlText = $p.xml; @{xml=$d.XmlText} | ConvertTo-Json -Compress
  } elseif ($p.operation -eq 'read') {
    try { $t = $f.GetTask($p.name); @{xml=$t.Xml} | ConvertTo-Json -Compress }
    catch {
      $errorObject = $_.Exception
      while ($errorObject.InnerException) { $errorObject = $errorObject.InnerException }
      if ($errorObject.HResult -eq -2147024894) { @{xml=$null} | ConvertTo-Json -Compress }
      else { throw }
    }
  } elseif ($p.operation -eq 'create') {
    if ($elevated) { throw 'elevated registration is forbidden' }
    # TASK_CREATE=2, TASK_LOGON_INTERACTIVE_TOKEN=3. Never update/overwrite an existing task.
    $null = $f.RegisterTask($p.name, $p.xml, 2, $sid, $null, 3, $null)
    @{ok=$true} | ConvertTo-Json -Compress
  } elseif ($p.operation -eq 'delete') {
    $t = $f.GetTask($p.name)
    if ($t.Xml -cne $p.expected) { throw 'changed' }
    $f.DeleteTask($p.name, 0); @{ok=$true} | ConvertTo-Json -Compress
  } else { throw 'operation' }
} catch { [Console]::Error.WriteLine('Windows startup operation failed'); exit 1 }
'''


def native(payload: dict) -> dict:
    if sys.platform != 'win32':
        raise StartupError('자동 시작 등록은 Windows PC에서만 사용할 수 있습니다.')
    executable = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    try:
        result = subprocess.run([str(executable), '-NoProfile', '-NonInteractive', '-Command', SCRIPT],
            input=json.dumps(payload), encoding='utf-8', capture_output=True, timeout=20, check=False)
        if result.returncode or len(result.stdout) > 131072:
            raise ValueError
        value = json.loads(result.stdout.lstrip('\ufeff'))
        if not isinstance(value, dict):
            raise TypeError
        return value
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        raise StartupError('작업 상태를 확인하지 못했습니다. 자동 재시도하지 않습니다. 새로고침 후 Windows 작업 스케줄러와 권한을 확인하세요.') from None


@dataclass(frozen=True)
class StartupPlan:
    root: Path
    data_dir: Path
    sid: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r'S-1-(?:5-21|12-1)-(?:[0-9]+-){3}[0-9]+', self.sid):
            raise StartupError('현재 Windows 사용자 계정을 확인하세요.')
        if self.sid.startswith('S-1-5-21-') and self.sid.endswith('-500'):
            raise StartupError('기본 제공 Administrator 대신 일반 Windows 사용자로 실행하세요.')
        for path in (self.root, self.data_dir):
            if not path.is_absolute() or any(c in str(path) for c in '\r\n\x00"'):
                raise StartupError('설치 및 저장 폴더 경로를 확인하세요.')

    @property
    def python(self) -> Path:
        return self.root / '.venv' / 'Scripts' / 'python.exe'

    @property
    def name(self) -> str:
        return 'NewsFlowAI-' + hashlib.sha256(self.sid.encode()).hexdigest()[:20]

    @property
    def owner(self) -> str:
        return 'NewsFlowAI startup/1 ' + hashlib.sha256(
            json.dumps([str(self.root), str(self.data_dir), self.sid]).encode()).hexdigest()

    @property
    def arguments(self) -> str:
        return subprocess.list2cmdline(['-m', 'newsflow.operations.autorun', '--data-dir', str(self.data_dir)])

    def xml(self) -> str:
        task = ET.Element('Task', xmlns='http://schemas.microsoft.com/windows/2004/02/mit/task', version='1.2')
        def node(parent, tag, value):
            ET.SubElement(parent, tag).text = value
        info = ET.SubElement(task, 'RegistrationInfo'); node(info, 'Description', self.owner)
        trigger = ET.SubElement(ET.SubElement(task, 'Triggers'), 'LogonTrigger')
        node(trigger, 'Enabled', 'true'); node(trigger, 'UserId', self.sid)
        principal = ET.SubElement(ET.SubElement(task, 'Principals'), 'Principal', id='Author')
        for tag, value in [('UserId',self.sid), ('LogonType','InteractiveToken'), ('RunLevel','LeastPrivilege')]:
            node(principal,tag,value)
        settings = ET.SubElement(task, 'Settings')
        for tag, value in SAFE_SETTINGS.items():
            node(settings,tag,value)
        action = ET.SubElement(ET.SubElement(task,'Actions',Context='Author'),'Exec')
        for tag, value in [('Command',str(self.python)),('Arguments',self.arguments),('WorkingDirectory',str(self.root))]:
            node(action,tag,value)
        return ET.tostring(task, encoding='unicode')

    def prepared(self) -> bool:
        # run.bat remains the only dependency installer; unattended startup never installs packages.
        try:
            digest = hashlib.sha256(str((3,12)).encode())
            for name in ('pyproject.toml','requirements-dev.lock'):
                digest.update((self.root/name).read_bytes())
            return (self.python.is_file() and not self.python.is_symlink()
                    and (self.root/'.venv/.newsflow-installed').read_text(encoding='ascii') == digest.hexdigest())
        except (OSError, ValueError):
            return False


SAFE_SETTINGS = {'MultipleInstancesPolicy':'IgnoreNew', 'DisallowStartIfOnBatteries':'false',
    'StopIfGoingOnBatteries':'false', 'AllowHardTerminate':'false', 'StartWhenAvailable':'false',
    'RunOnlyIfNetworkAvailable':'false', 'AllowStartOnDemand':'true', 'Enabled':'true',
    'Hidden':'false', 'RunOnlyIfIdle':'false', 'WakeToRun':'false', 'ExecutionTimeLimit':'PT0S', 'Priority':'7'}


def owned(plan: StartupPlan, xml: str) -> bool:
    """Reject foreign, altered or elevated tasks. Only understood Scheduler defaults are allowed."""
    try:
        root = fromstring(xml)
        for element in root.iter():
            element.tag = element.tag.rsplit('}',1)[-1]
        if root.tag != 'Task':
            return False
        expected = fromstring(plan.xml())
        for element in expected.iter():
            element.tag = element.tag.rsplit('}',1)[-1]
        # Compare operational sections including child counts. Scheduler may add documented defaults.
        for path in ['RegistrationInfo/Description','Triggers','Principals','Actions']:
            left, right = root.find(path), expected.find(path)
            if left is None or right is None or tree(left) != tree(right):
                return False
        settings = root.find('Settings')
        if settings is None:
            return False
        values = {c.tag:c.text for c in settings}
        if any(values.get(k) != v for k,v in SAFE_SETTINGS.items()):
            return False
        # IdleSettings is inert with RunOnlyIfIdle=false, but disallow every other unknown setting.
        return all(c.tag in SAFE_SETTINGS or c.tag == 'IdleSettings' for c in settings)
    except (ValueError, ET.ParseError):
        return False


def tree(element) -> tuple:
    return (element.tag, tuple(sorted(element.attrib.items())), (element.text or '').strip(),
            tuple(tree(child) for child in element))


class TaskScheduler(Protocol):
    def read(self, plan: StartupPlan) -> str | None: ...
    def create(self, plan: StartupPlan) -> None: ...
    def delete(self, plan: StartupPlan, expected: str) -> None: ...


class WindowsTaskScheduler:
    def read(self, plan: StartupPlan) -> str | None:
        value = native({'operation':'read','name':plan.name,'sid':plan.sid}).get('xml', 'invalid')
        if value is not None and not isinstance(value,str):
            raise StartupError('작업 상태 응답을 확인할 수 없습니다.')
        return value

    def create(self, plan: StartupPlan) -> None:
        native({'operation':'create','name':plan.name,'sid':plan.sid,'xml':plan.xml()})

    def delete(self, plan: StartupPlan, expected: str) -> None:
        native({'operation':'delete','name':plan.name,'sid':plan.sid,'expected':expected})


class FakeTaskScheduler:
    """Test injection only; never selectable through GUI/environment."""
    def __init__(self):
        self.xml: str | None = None
        self.calls: list[str] = []

    def read(self, plan: StartupPlan) -> str | None:
        return self.xml

    def create(self, plan: StartupPlan) -> None:
        if self.xml is not None:
            raise StartupError('이미 등록된 작업입니다.')
        self.calls.append('create'); self.xml = plan.xml()

    def delete(self, plan: StartupPlan, expected: str) -> None:
        if self.xml != expected:
            raise StartupError('작업이 변경되었습니다.')
        self.calls.append('delete'); self.xml = None


class StartupService:
    def __init__(self, plan: StartupPlan, adapter: TaskScheduler):
        self.plan, self.adapter = plan, adapter

    def view(self) -> dict:
        xml = self.adapter.read(self.plan)
        status = 'disabled' if xml is None else 'enabled' if owned(self.plan,xml) else 'conflict'
        revision = hashlib.sha256((self.plan.owner + (xml or '')).encode()).hexdigest()
        return {'status':status, 'revision':revision, 'prepared':self.plan.prepared(), 'task_name':self.plan.name}

    def change(self, action: str, revision: str, consent: bool) -> None:
        if not consent or action not in {'register','remove'}:
            raise StartupError('자동 시작 변경 내용을 확인하고 직접 동의해 주세요.')
        try:
            with FileLock(str(self.plan.data_dir/'startup-settings.lock')).acquire(timeout=0):
                state = self.view()
                if revision != state['revision'] or state['status'] == 'conflict':
                    raise StartupError('작업이 변경되었거나 다른 설치의 작업입니다. 새로고침하고 확인하세요.')
                if action == 'register':
                    if state['status'] != 'disabled' or not state['prepared']:
                        raise StartupError('먼저 run.bat로 설치를 완료하세요. 이미 등록된 작업은 덮어쓰지 않습니다.')
                    self.adapter.create(self.plan)
                    if self.view()['status'] != 'enabled':
                        raise StartupError('등록 결과를 확인하지 못했습니다. 다시 등록하지 말고 상태를 확인하세요.')
                else:
                    xml = self.adapter.read(self.plan)
                    if not xml or not owned(self.plan,xml) or hashlib.sha256((self.plan.owner+xml).encode()).hexdigest() != revision:
                        raise StartupError('해제할 작업을 다시 확인하세요.')
                    self.adapter.delete(self.plan,xml)
                    if self.view()['status'] != 'disabled':
                        raise StartupError('해제 결과를 확인하지 못했습니다. 상태를 다시 확인하세요.')
        except (Timeout, OSError):
            raise StartupError('다른 변경이 진행 중이거나 저장 권한이 없습니다. 잠시 후 상태를 확인하세요.') from None


def local_service(data_dir: Path) -> StartupService:
    identity = native({'operation':'identity'})
    if identity.get('elevated') is not False:
        raise StartupError('관리자 권한 없이 run.bat를 실행한 뒤 자동 시작을 설정하세요.')
    sid = identity.get('sid','')
    return StartupService(StartupPlan(Path(__file__).resolve().parents[3], data_dir.resolve(), sid), WindowsTaskScheduler())
