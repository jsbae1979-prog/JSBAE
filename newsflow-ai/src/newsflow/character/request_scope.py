"""Identify explicit manual character operations without storing their content.

Saved provider approval and the per-request ceiling remain authoritative.
An unrelated completed unknown journal is retained, never replayed or charged as
zero. The same operation, an active request, or an unclassifiable unknown stays blocked.
"""
import hashlib
import json
import re
from .schema import CharacterError

EPISODE=re.compile(r"episode:([a-f0-9]{32}):script:[1-9][0-9]*\Z")

def operation_for(*,kind,instruction,payload,model,request_id,image_bytes=None):
    match=EPISODE.fullmatch(request_id)
    action="analysis" if kind=="analysis" else "story" if match else "topics"
    document={"action":action,"model":model}
    if action=="story":document["job_id"]=match.group(1)
    else:
        document.update(instruction=instruction,payload=payload,
                        image_sha256=hashlib.sha256(image_bytes).hexdigest() if image_bytes is not None else None)
    key=hashlib.sha256(json.dumps(document,sort_keys=True,ensure_ascii=False,separators=(",",":"),default=str).encode()).hexdigest()
    return {"version":1,"action":action,"key":key,"job_id":match.group(1) if match else ""}

def validate_operation(value,kind,request_id):
    if (not isinstance(value,dict) or set(value)!={"version","action","key","job_id"}
        or value["version"]!=1 or value["action"] not in {"analysis","topics","story"}
        or not isinstance(value["key"],str) or not re.fullmatch(r"[a-f0-9]{64}",value["key"])
        or (value["action"]=="analysis")!=(kind=="analysis")):
        raise CharacterError("budget")
    if value["action"]=="story":
        match=EPISODE.fullmatch(request_id)
        if not match or value["job_id"]!=match.group(1):raise CharacterError("budget")
    elif value["job_id"]!="" or EPISODE.fullmatch(request_id):raise CharacterError("budget")
    return dict(value)

def unrelated_unknown_ids(rows,operation,acknowledged=frozenset()):
    result=set()
    for row in rows:
        if row.status!="unknown" or row.finished_at is None or row.id not in acknowledged:continue
        saved=(row.bounds or {}).get("character_operation")
        if isinstance(saved,dict):
            try:validate_operation(saved,row.kind,row.request_id)
            except CharacterError:continue
            same_job=operation["action"]==saved["action"]=="story" and operation["job_id"]==saved["job_id"]
            if not same_job and saved["key"]!=operation["key"]:result.add(row.id)
        else:
            legacy=EPISODE.fullmatch(row.request_id)
            if legacy and (operation["action"]!="story" or legacy.group(1)!=operation["job_id"]):result.add(row.id)
    return result


def previously_reviewed_ids(session,settings,rows):
    """Reuse only an explicit recorded review of the exact unchanged old journal.

    New unknown results, changed fingerprints and unreviewed records are never
    acknowledged by a stored provider setting or by this helper.
    """
    from sqlalchemy import select
    from newsflow.db.models import AuditLog
    from newsflow.intelligence.api_settings import _unknown_fingerprint
    fingerprints={row.id:_unknown_fingerprint(row) for row in rows
                  if row.status=="unknown" and row.finished_at is not None}
    result=set()
    for entry in session.scalars(select(AuditLog).where(AuditLog.event=="api_episode_story_once_ack")):
        try:value=json.loads(entry.message)
        except (TypeError,ValueError):continue
        if (not isinstance(value,dict) or value.get("scope")!="new_episode_story_once"
                or value.get("provider")!=settings.provider or value.get("model")!=settings.model):continue
        known=value.get("unknowns")
        if not isinstance(known,dict):continue
        result.update(identifier for identifier,fp in known.items()
                      if identifier in fingerprints and fingerprints[identifier]==fp)
    return result
