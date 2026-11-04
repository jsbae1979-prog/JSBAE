"""Owner-specific opt-in. Configuration does not start a listener or external connection."""

import json
from pathlib import Path

from newsflow.db.models import AppSetting

from .contracts import MetaError
from .local_images import MAX_IMAGE, LocalImageSession


class LocalImageDelivery:
    def __init__(self, accounts, factory=None, *, verify=None):
        self.accounts, self.factory, self.verify = accounts, factory, verify
        self.key = "meta.local-images." + accounts.owner
        self.session = None

    def config(self):
        with self.accounts.sessions() as db:
            row = db.get(AppSetting, self.key)
            return json.loads(row.value) if row else {"enabled": False, "port": 18769}

    def enabled(self):
        return self.config().get("enabled") is True

    def status(self):
        cfg = self.config()
        available = bool(self.factory and self.factory().available())
        return {
            **cfg,
            "available": available,
            "active": bool(self.session and self.session.bridge and self.session.bridge.alive()),
        }

    def ready(self):
        return self.enabled() and self.status()["available"]

    def configure(self, enabled, port):
        if (
            type(enabled) is not bool
            or type(port) is not int
            or not 1024 <= port <= 65535
            or port in {8765, 18768}
        ):
            raise MetaError("invalid")
        if enabled and not (self.factory and self.factory().available()):
            raise MetaError("configuration")
        with self.accounts.lock:
            cfg = self.config()
            if self.session and self.session.bridge and (not enabled or cfg["port"] != port):
                raise MetaError("pending")  # Never break a container's image fetch while changing settings.
            with self.accounts.sessions.begin() as db:
                row = db.get(AppSetting, self.key)
                value = json.dumps({"enabled": enabled, "port": port})
                if row:
                    row.value = value
                else:
                    db.add(AppSetting(key=self.key, value=value))

    def upload(self, path, digest, kind):
        if kind != "image" or not self.ready():
            raise MetaError("configuration")
        path = Path(path)
        root = self.accounts.root.resolve()
        if not path.resolve().is_relative_to(root):
            raise MetaError("media")
        for part in (path, *path.parents):
            if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
                raise MetaError("media")
            if part == root:
                break
        with path.open("rb") as file:
            raw = file.read(MAX_IMAGE + 1)
        if self.session is None:
            kwargs = {"verify": self.verify} if self.verify else {}
            self.session = LocalImageSession(self.factory, self.config()["port"], **kwargs)
        return self.session.offer(raw, digest)

    def close(self):
        if self.session:
            self.session.close()
