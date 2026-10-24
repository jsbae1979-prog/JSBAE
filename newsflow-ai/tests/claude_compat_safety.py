"""Opt-in isolation guard for the local-source compatibility test run."""
import http.client
import ipaddress
import os
import socket

import pytest


@pytest.fixture(scope="session", autouse=True)
def isolate_compatibility_run():
    with pytest.MonkeyPatch.context() as patch:
        for name in tuple(os.environ):
            if name.startswith("NEWSFLOW_"):
                patch.delenv(name)

        def denied(*args, **kwargs):
            raise AssertionError("External requests are forbidden in isolated compatibility tests")

        patch.setattr("urllib.request.OpenerDirector.open", denied)
        connect = http.client.HTTPConnection.connect
        socket_connect = socket.create_connection

        def loopback_host(host):
            try:
                return ipaddress.ip_address(host).is_loopback
            except ValueError:
                return False

        def local_http(connection):
            if not loopback_host(connection.host) or connection._tunnel_host:
                return denied()
            return connect(connection)

        def local_socket(address, *args, **kwargs):
            if not loopback_host(address[0]):
                return denied()
            return socket_connect(address, *args, **kwargs)

        patch.setattr("socket.create_connection", local_socket)
        patch.setattr("http.client.HTTPConnection.connect", local_http)
        patch.setattr("http.client.HTTPSConnection.connect", denied)
        patch.setattr("httpx.HTTPTransport.handle_request", denied)
        patch.setattr("httpx.AsyncHTTPTransport.handle_async_request", denied)
        patch.setattr("newsflow.scheduler.service.Scheduler.start", lambda self: None)
        patch.setattr("newsflow.video.ai.service.AIVideoCoordinator.start", lambda self: None)
        patch.setattr("newsflow.publishing.calendar.PublishingCalendar.start", lambda self: None)
        yield
