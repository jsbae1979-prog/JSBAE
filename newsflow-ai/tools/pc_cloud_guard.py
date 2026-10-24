"""Test-process audit barrier: sockets cannot reach providers or the operating app."""
import ipaddress
import json
import os
import sys
from pathlib import Path

attempts = []


def audit(event, args):
    if event == "socket.connect":
        address = args[1]
        if not isinstance(address, tuple):
            return
        host, port = str(address[0]), address[1]
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = host == "localhost"
        if not local or port == 8765:
            attempts.append({"event": event, "reason": "non-test-network"})
            raise PermissionError("Isolated validation forbids external/operating connections")
    if event == "socket.getaddrinfo":
        host = args[0]
        if host in (None, "", "localhost"):
            return
        try:
            ipaddress.ip_address(str(host))
        except ValueError:
            attempts.append({"event": event, "reason": "external-dns"})
            raise PermissionError("Isolated validation forbids external DNS")
    if event == "subprocess.Popen":
        executable = Path(str(args[0])).stem.lower()
        if executable in {"codex", "claude"}:
            attempts.append({"event": event, "reason": "provider-cli"})
            raise PermissionError("Provider CLI execution forbidden in isolated validation")


def pytest_configure(config):
    if os.environ.get("NEWSFLOW_PC_CLOUD_ISOLATED") != "1":
        raise RuntimeError("Use tools/pc_cloud_validate.py for the isolated environment")
    sys.addaudithook(audit)


def pytest_sessionfinish(session, exitstatus):
    output = Path(os.environ["NEWSFLOW_VALIDATION_OUTPUT"])
    output.mkdir(parents=True, exist_ok=True)
    (output / "network-guard.json").write_text(json.dumps({
        "blocked_attempts": attempts, "external_connections_allowed": False,
        "operating_port_allowed": False, "pytest_exitstatus": exitstatus,
    }, indent=2), encoding="utf-8")
