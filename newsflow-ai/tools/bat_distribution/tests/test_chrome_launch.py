"""Focused Chrome launch tests: synthetic URLs and fake process only."""
from pathlib import Path
from types import SimpleNamespace
import subprocess
import pytest
from bat_distribution import windows_live as live

URL = 'http://127.0.0.1:18768/__local/connect#' + 'a' * 43

@pytest.fixture
def installed(monkeypatch):
    monkeypatch.setattr(Path, 'is_file', lambda self: True)
    monkeypatch.setattr(live, 'ordinary_absolute', lambda path: path)

def test_direct_chrome_launch_no_shell_or_output(installed, monkeypatch, capsys):
    calls = []
    def spawn(args, **kw):
        calls.append((args, kw))
        return SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(subprocess, 'Popen', spawn)
    assert live.open_chrome_session(URL) is True
    args, options = calls[0]
    assert len(calls) == 1
    assert args == [str(Path('C:/Program Files/Google/Chrome/Application/chrome.exe')), '--new-window', URL]
    assert options == dict(shell=False, stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           close_fds=True)
    assert capsys.readouterr() == ('', '')

@pytest.mark.parametrize('url', [
    'https://127.0.0.1:18768/__local/connect#' + 'a'*43,
    'http://outside.invalid:18768/__local/connect#' + 'a'*43,
    'http://127.0.0.1:8765/__local/connect#' + 'a'*43,
    'http://127.0.0.1:18768/studio/dashboard#' + 'a'*43,
    'http://127.0.0.1:18768/__local/connect?token=x#' + 'a'*43,
    'http://user@127.0.0.1:18768/__local/connect#' + 'a'*43,
    'http://127.0.0.1:18768/__local/connect',
    'http://127.0.0.1:18768/__local/connect#' + 'a'*44,
    'http://127.0.0.1:not-a-port/__local/connect#' + 'a'*43,
])
def test_invalid_launch_url_never_starts_process(monkeypatch, url):
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('must not launch'))
    assert live.open_chrome_session(url) is False

def test_missing_chrome_has_no_default_browser_fallback(monkeypatch):
    monkeypatch.setattr(Path, 'is_file', lambda self: False)
    monkeypatch.setattr(live, 'ordinary_absolute', lambda path: path)
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('must not launch'))
    assert live.open_chrome_session(URL) is False

def test_native_error_does_not_echo_authentication(installed, monkeypatch, capsys):
    def denied(*args, **kwargs):
        raise OSError('synthetic native error containing ' + URL)
    monkeypatch.setattr(subprocess, 'Popen', denied)
    assert live.open_chrome_session(URL) is False
    assert capsys.readouterr() == ('', '')

def test_chrome_immediate_failure_is_not_success(installed, monkeypatch):
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: SimpleNamespace(poll=lambda: 1))
    assert live.open_chrome_session(URL) is False
