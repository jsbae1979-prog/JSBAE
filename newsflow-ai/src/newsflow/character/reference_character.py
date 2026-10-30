"""Image-bound episode identity without registration or paid image analysis.

These are writing directions, not claimed visual/personality observations.
The original image goes only to the selected video provider, never the writer.
"""
import hashlib
from .registry import ASSET_ID, CharacterProfile
from .schema import CharacterError

def reference_snapshot(raw,asset):
    sha=hashlib.sha256(raw).hexdigest()
    if not isinstance(asset,str) or not ASSET_ID.fullmatch(asset) or asset!=f"studio-{sha}.png":
        raise CharacterError("reference")
    profile=CharacterProfile.model_validate({
      "name_ko":"주인공","species":"",
      "appearance":"Use the exact character shown in the supplied reference image. Preserve its visible identity, proportions, colors, clothing and accessories without inventing hidden traits.",
      "personality":"입력한 주제에 맞는 행동과 표정으로 표현합니다.",
      "comedy_formula":{"world":"","setup":"사용자가 입력한 주제의 상황","reaction":"대사 없이 표정과 몸짓으로 상황에 반응"},
      "style_lock":"Match the supplied reference image's original visual style.",
      "supporting_cast":[],"audience":"general","made_for_kids":False}).model_dump()
    return {**profile,"id":"ref_"+sha[:32],"revision":0,"asset":asset,
            "reference_image":{"sha256":sha},"snapshot_kind":"image_topic"}
