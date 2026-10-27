import socket
import subprocess
import urllib.request

import pytest


@pytest.fixture(autouse=True)
def deny_external(monkeypatch):
 def denied(*a,**k):raise AssertionError("Network/process use forbidden in TOP3 unit tests")
 monkeypatch.setattr(socket.socket,"connect",denied)
 monkeypatch.setattr(socket,"getaddrinfo",denied)
 monkeypatch.setattr(subprocess,"Popen",denied)
 monkeypatch.setattr(urllib.request.OpenerDirector,"open",denied)
