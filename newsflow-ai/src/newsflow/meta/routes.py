"""Authenticated local GUI API. Global LocalAccess, Origin and CSRF middleware apply."""

import json
from threading import RLock

from fastapi import APIRouter, Form, HTTPException, Request

from .contracts import MetaError
from .graph import MetaGraph
from .media import MetaDelivery, resolve_content
from .publishing import MetaPublishing
from .service import MetaConnections

router = APIRouter()
_lock = RLock()


def services(request):
    state = request.app.state
    with _lock:
        if not hasattr(state, "meta_connections"):
            from .vault import MetaVault, local_owner

            owner = local_owner()
            vault = MetaVault(
                state.config.data_dir / "meta-oauth",
                owner,
                native_factory=getattr(state, "meta_native_factory", None),
            )
            accounts = MetaConnections(state.sessions, state.config.data_dir, owner=owner, vault=vault)
            delivery = MetaDelivery(accounts)

            class Graph:
                supports_direct = staticmethod(MetaGraph.supports_direct)

                def call(self, *args):
                    return MetaGraph(accounts.config()["graphVersion"]).call(*args)

                def upload_file(self, *args):
                    return MetaGraph(accounts.config()["graphVersion"]).upload_file(*args)

                def upload_reel(self, *args):
                    return MetaGraph(accounts.config()["graphVersion"]).upload_reel(*args)

            publisher = MetaPublishing(accounts, Graph(), lambda key: resolve_content(state, key), delivery)
            publisher.recover()  # Mark interrupted POSTs unknown; never resume them.
            state.meta_connections, state.meta_publishing = accounts, publisher
        return state.meta_connections, state.meta_publishing


def safely(operation):
    try:
        return operation()
    except MetaError as error:
        raise HTTPException(422, {
            "code": error.code, "message": str(error), "diagnostics": error.diagnostics,
        }) from None
    except Exception:  # noqa: BLE001 - never expose provider, credential or native exception details
        raise HTTPException(422, {"code": "unknown", "message": str(MetaError())}) from None


@router.get("/api/meta/status")
def status(request: Request):
    def run():
        accounts, publisher = services(request)
        return {
            **accounts.status(),
            "mediaReady": publisher.delivery.ready(),
            "executionReady": getattr(request.app.state, "meta_execution_enabled", True),
            "publications": publisher.list(),
            "storageReady": publisher.storage_states(),
            "transferModes": publisher.transfer_modes(),
            "automaticStorageReady": bool(
                getattr(publisher.delivery, "automatic", None) and publisher.delivery.automatic.ready()
            ),
        }

    return safely(run)


@router.post("/api/meta/config")
def configure(
    request: Request,
    app_id: str = Form(max_length=40),
    config_id: str = Form(max_length=40),
    graph_version: str = Form(max_length=10),
    relay_origin: str = Form(max_length=300),
):
    def run():
        accounts, _ = services(request)
        accounts.configure(
            {
                "appId": app_id,
                "configId": config_id,
                "graphVersion": graph_version,
                "relayOrigin": relay_origin,
            }
        )
        return {"saved": True}

    return safely(run)


@router.post("/api/meta/media-config")
def media_config(request: Request, origin: str = Form(max_length=300), credential: str = Form()):
    return safely(lambda: services(request)[1].delivery.configure(origin, credential) or {"saved": True})


@router.post("/api/meta/automatic-storage")
def automatic_storage(
    request: Request,
    endpoint: str = Form(max_length=300),
    region: str = Form(max_length=40),
    bucket: str = Form(max_length=63),
    access_key: str = Form(),
    secret_key: str = Form(),
):
    return safely(
        lambda: (
            services(request)[1].delivery.automatic.configure(
                endpoint, region, bucket, access_key, secret_key
            )
            or {"saved": True}
        )
    )


@router.post("/api/meta/import-token")
def import_token(
    request: Request,
    token: str = Form(),
    consent: bool = Form(False),
    reconnect: str = Form("", max_length=32),
):
    return safely(
        lambda: (
            services(request)[0].import_token(token, consent=consent, reconnect=reconnect or None)
            or {"discovered": True}
        )
    )


@router.post("/api/meta/connect")
def connect(request: Request, consent: bool = Form(False), reconnect: str = Form("", max_length=32)):
    return safely(
        lambda: services(request)[0].begin(consent=consent, reconnect=reconnect or None) or {"started": True}
    )


@router.post("/api/meta/select-page")
def select_page(request: Request, page_id: str = Form(max_length=40)):
    return safely(lambda: services(request)[0].select_page(page_id) or {"selected": True})


@router.post("/api/meta/cancel")
def cancel(request: Request):
    return safely(lambda: services(request)[0].cancel() or {"cancelled": True})


@router.post("/api/meta/accounts/{identifier}/rename")
def rename(request: Request, identifier: str, label: str = Form(max_length=200)):
    return safely(lambda: services(request)[0].rename(identifier, label) or {"saved": True})


@router.post("/api/meta/accounts/{identifier}/disconnect")
def disconnect(request: Request, identifier: str, consent: bool = Form(False)):
    def run():
        if consent is not True:
            raise MetaError("consent")
        services(request)[0].disconnect(identifier)
        return {"disconnected": True}

    return safely(run)


@router.post("/api/meta/publications/prepare")
def prepare(
    request: Request,
    content_id: str = Form(max_length=100),
    targets: str = Form(max_length=4096),
    caption: str = Form(max_length=2200),
    reviewed: bool = Form(False),
):
    return safely(
        lambda: services(request)[1].prepare(content_id, json.loads(targets), caption, reviewed=reviewed)
    )


@router.post("/api/meta/publications/{identifier}/storage")
def storage(
    request: Request,
    identifier: str,
    put_url: str = Form(),
    get_url: str = Form(),
    expires: str = Form(max_length=40),
):
    return safely(
        lambda: (
            services(request)[1].configure_storage(identifier, put_url, get_url, expires) or {"saved": True}
        )
    )


@router.post("/api/meta/publications/{identifier}/send")
def send(request: Request, identifier: str, consent: bool = Form(False)):
    return safely(lambda: services(request)[1].send(identifier, consent=consent))


@router.post("/api/meta/publications/{identifier}/check")
def check(request: Request, identifier: str):
    return safely(lambda: services(request)[1].check(identifier))


@router.post("/api/meta/publications/{identifier}/publish")
def publish(request: Request, identifier: str, consent: bool = Form(False)):
    return safely(lambda: services(request)[1].publish(identifier, consent=consent))
