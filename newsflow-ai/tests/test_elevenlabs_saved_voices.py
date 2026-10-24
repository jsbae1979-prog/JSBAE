"""My Voices request filtering only; no extra account lookup and no existing-cache mutation on GET."""

import io
import json
import urllib.request
from urllib.parse import parse_qs, urlsplit

import pytest
import test_elevenlabs_voices as voices_tests

from newsflow.video.tts import TTSError

catalog = voices_tests.catalog
no_real_network = voices_tests.no_real_network


def test_saved_filter_in_first_and_manual_next_page_without_extra_call(catalog, monkeypatch):
    requests = []

    def fake_open(self, request, timeout):
        requests.append(request)
        data = voices_tests.payload("저장한 음성", "savedA") if len(requests) == 1 else (
            voices_tests.payload("컬렉션에 저장한 기본 음성", "savedDefault"))
        if len(requests) == 1:
            data.update(has_more=True, next_page_token="saved-page-2")
        return io.BytesIO(json.dumps(data).encode())

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", fake_open)
    first = catalog.load()
    assert first["voice_type"] == "saved" and len(requests) == 1
    second = catalog.load(more=True)
    assert len(requests) == 2 and second["voice_type"] == "saved"
    assert len(second["voices"]) == 2  # Do not discard a saved default just because it is a default.
    for index, request in enumerate(requests):
        query = parse_qs(urlsplit(request.full_url).query)
        assert request.get_method() == "GET" and urlsplit(request.full_url).path == "/v2/voices"
        assert query["voice_type"] == ["saved"]
        assert query.get("next_page_token") == (["saved-page-2"] if index else None)
    catalog.cached()
    assert len(requests) == 2


def test_unfiltered_legacy_cache_is_preserved_and_cannot_mix_page_tokens(catalog):
    catalog.transport = lambda token: dict(voices_tests.payload(), has_more=True, next_page_token="old-token")
    catalog.load()
    path = catalog.root / "voices.json"
    legacy = json.loads(path.read_text(encoding="utf-8"))
    legacy.pop("voice_type")
    path.write_text(json.dumps(legacy), encoding="utf-8")
    before = path.read_bytes()
    assert catalog.cached()["voices"] == legacy["voices"] and path.read_bytes() == before
    calls = []
    catalog.transport = lambda token: calls.append(token) or voices_tests.payload("내 음성", "savedOnly")
    with pytest.raises(TTSError, match="기존 전체 목록"):
        catalog.load(more=True)
    assert calls == [] and path.read_bytes() == before
    result = catalog.load()
    assert calls == [None] and result["voice_type"] == "saved"
    assert [v["voice_id"] for v in result["voices"]] == ["savedOnly"]
