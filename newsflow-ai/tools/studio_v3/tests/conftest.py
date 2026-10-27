import pytest


@pytest.fixture(autouse=True)
def deny_external_calls(monkeypatch):
    import socket
    import subprocess
    def denied(*args,**kwargs):raise AssertionError("Read-model tests may not open external connections or processes")
    monkeypatch.setattr(socket.socket,"connect",denied)
    monkeypatch.setattr(subprocess,"Popen",denied)
