"""Free copy helpers and manually reported feed performance. No provider access."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import json
import re
from uuid import uuid4
from filelock import Timeout
from newsflow.db.models import AppSetting
from newsflow.publishing.service import PublishingError, reject_secrets

PART_LIMITS = {"lead": 180, "facts": 1200, "meaning": 300, "question": 180}


def caption_parts(value):
    if not isinstance(value, dict) or set(value) - PART_LIMITS.keys():
        raise PublishingError("캡션 구성 항목을 확인하세요.")
    result = {}
    for key, limit in PART_LIMITS.items():
        text = value.get(key, "")
        if not isinstance(text, str) or len(text) > limit or any(ord(c) < 32 and c != "\n" for c in text):
            raise PublishingError("캡션 구성의 길이와 입력 형식을 확인하세요.")
        reject_secrets(text)
        result[key] = text.strip()
    return result


def compose_caption(value):
    parts = caption_parts(value)
    if not parts["lead"] and not parts["facts"]:
        raise PublishingError("캡션의 첫 문장 또는 핵심 사실을 입력하세요.")
    text = "\n\n".join(parts[k] for k in PART_LIMITS if parts[k])
    if len(text) > 1800:
        raise PublishingError("캡션이 1800자를 넘습니다. 문구를 직접 조정하세요.")
    return text


def copy_options(source, item, draft):
    """Exact stored phrases only; never fabricate a hook or translate implicitly."""
    first = re.split(r"(?<=[.!?。])\s+|\n", source.get("body", ""))[0]
    values = [("현재 편집 제목", draft["title"]), ("저장된 제목", item["content"]["title"]),
              ("기사 원제", source["title"]), ("요약 첫 문장", first)]
    candidates, seen = [], set()
    for label, text in values:
        normalized = " ".join(text.split())
        if not normalized or normalized in seen or len(text) > 140:
            continue
        seen.add(normalized)
        candidates.append({"label": label, "text": text, "characters": len(text),
                           "korean": bool(re.search(r"[가-힣]", text))})
        if len(candidates) == 3:
            break
    return {"titleCandidates": candidates, "paid": False}


def _time(value):
    if not isinstance(value, str) or len(value) > 40:
        raise PublishingError("게시·측정 시각을 확인하세요.")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError()
        return stamp.astimezone(timezone.utc)
    except ValueError:
        raise PublishingError("시간대가 있는 게시·측정 시각을 입력하세요.") from None


def metric_input(value, now):
    names = {"version", "url", "publishedAt", "observedAt", "reach", "saves", "shares", "follows", "publishedConfirmed"}
    if not isinstance(value, dict) or set(value) != names or value["publishedConfirmed"] is not True:
        raise PublishingError("실제 게시한 콘텐츠의 성과만 기록하세요.")
    if type(value["version"]) is not int or value["version"] < 0:
        raise PublishingError("게시한 이미지 버전을 선택하세요.")
    url = value["url"]
    if not isinstance(url, str) or not re.fullmatch(r"https://(?:www\.)?instagram\.com/p/[A-Za-z0-9_-]{1,80}/?", url):
        raise PublishingError("Instagram 이미지 게시물 주소를 입력하세요. 계정·인증 주소는 저장하지 않습니다.")
    posted, observed = _time(value["publishedAt"]), _time(value["observedAt"])
    if posted > observed or observed > now:
        raise PublishingError("게시 후 측정한 과거 시각을 입력하세요.")
    counts = {}
    for key in ("reach", "saves", "shares", "follows"):
        number = value[key]
        if number is not None and (type(number) is not int or not 0 <= number <= 1_000_000_000):
            raise PublishingError("성과 수치는 0 이상의 정수로 입력하고, 미확인은 비워 두세요.")
        counts[key] = number
    if all(v is None for v in counts.values()):
        raise PublishingError("확인한 성과 수치를 하나 이상 입력하세요.")
    return {"version": value["version"], "url": url.replace("www.", "").rstrip("/"),
            "publishedAt": posted.isoformat(), "observedAt": observed.isoformat(), **counts}


def metric_view(row):
    reach = row["reach"]
    rates = {key: float((Decimal(row[key]) * 100 / Decimal(reach)).quantize(Decimal(".01")))
             if reach and row[key] is not None else None for key in ("saves", "shares", "follows")}
    hours = (_time(row["observedAt"]) - _time(row["publishedAt"])).total_seconds() / 3600
    return {**row, "rates": rates, "elapsedHours": round(hours, 1), "source": "manual", "verifiedByPlatform": False}


class FeedPerformance:
    def __init__(self, designs, *, now=None):
        self.designs = designs
        self.feeds = designs.feeds
        self.now = now or (lambda: datetime.now(timezone.utc))

    def key(self, batch, rank):
        return f"feed-performance:{batch}:{rank}"

    def load(self, batch, rank):
        self.designs.source(batch, rank)
        with self.feeds.sessions() as session:
            row = session.get(AppSetting, self.key(batch, rank))
            return json.loads(row.value) if row else {"revision": 0, "records": []}

    def view(self, batch, rank):
        value = self.load(batch, rank)
        return {**value, "records": [metric_view(r) for r in value["records"]], "networkRequests": 0}

    def save(self, batch, rank, revision, value):
        entry = metric_input(value, self.now())
        try:
            with self.feeds.lock:
                current = self.load(batch, rank)
                if entry["version"]:
                    version = self.designs.version(batch, rank, entry["version"])
                    identity = {"style": version["design"]["style"], "imageSha256": version["sha256"]}
                else:
                    from hashlib import sha256
                    path = self.feeds.path(batch, rank)
                    row, _, _ = self.designs.source(batch, rank)
                    identity = {"style": row.options.get("feed_style", "legacy"), "imageSha256": sha256(path.read_bytes()).hexdigest()}
                record = {**entry, **identity}
                for old in current["records"]:
                    if old["url"] == entry["url"]:
                        if (old["version"], old["imageSha256"]) != (entry["version"], identity["imageSha256"]):
                            raise PublishingError("같은 게시물은 동일 이미지 버전으로 기록하세요.")
                        if old["observedAt"] == entry["observedAt"]:
                            if {k: v for k, v in old.items() if k != "id"} == record:
                                return self.view(batch, rank)
                            raise PublishingError("같은 측정 시각의 기록이 있습니다. 원래 기록을 보존합니다.")
                if type(revision) is not int or current["revision"] != revision:
                    raise PublishingError("다른 화면에서 성과가 저장됐습니다. 다시 불러오세요.")
                if len(current["records"]) >= 200:
                    raise PublishingError("이 뉴스의 성과 기록이 200건입니다.")
                updated = deepcopy(current)
                updated["records"].append({"id": uuid4().hex, **record})
                updated["revision"] += 1
                with self.feeds.sessions.begin() as session:
                    row = session.get(AppSetting, self.key(batch, rank))
                    encoded = json.dumps(updated, ensure_ascii=False)
                    if row:
                        row.value = encoded
                    else:
                        session.add(AppSetting(key=self.key(batch, rank), value=encoded))
        except Timeout:
            raise PublishingError("편집 작업이 진행 중입니다. 잠시 후 확인하세요.") from None
        return self.view(batch, rank)
