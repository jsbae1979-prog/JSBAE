"""Identical Cloud browser selection for both immutable-source comparisons.
No assertions, test collection, application security or network policy are changed.
"""
import os
from playwright.sync_api import BrowserType

_original_launch = BrowserType.launch

def _launch(self, *args, **kwargs):
    if self.name == "chromium" and kwargs.get("channel") == "chrome":
        kwargs.pop("channel")
        kwargs["executable_path"] = os.environ["NEWSFLOW_TEST_BROWSER_EXECUTABLE"]
    return _original_launch(self, *args, **kwargs)

BrowserType.launch = _launch
