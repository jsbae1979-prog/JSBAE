"""Opt-in isolation guard for the local-source compatibility test run."""
import os

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
        patch.setattr("http.client.HTTPConnection.connect", denied)
        patch.setattr("http.client.HTTPSConnection.connect", denied)
        patch.setattr("httpx.HTTPTransport.handle_request", denied)
        patch.setattr("httpx.AsyncHTTPTransport.handle_async_request", denied)
        patch.setattr("newsflow.scheduler.service.Scheduler.start", lambda self: None)
        patch.setattr("newsflow.video.ai.service.AIVideoCoordinator.start", lambda self: None)
        yield
