"""Feed copy produced inside the existing TOP 3 analysis, never an extra API call."""
from pydantic import BaseModel, ConfigDict, Field

INSTRUCTION = (
    "For EACH selected ranking group, also return feed_copy with title and description in Korean. "
    "Write an independently worded Instagram headline (2-3 short lines, at most 80 characters) and "
    "a core explanation (1-2 lines, at most 140 characters) inside this same analysis response. "
    "First identify facts from ONLY that group's supplied titles/summaries, then consider alternative "
    "headlines and select one. Do not copy the original title, its opening clause, distinctive metaphors "
    "or quotations; do not merely replace synonyms or punctuation. Keep necessary proper names and "
    "technical terms. The explanation adds a supported detail rather than repeating the headline. "
    "Keep actors, dates, units, numeric notation, attribution and event status unchanged. "
    "A proposal is not approval, a plan is not implementation, and a pending election is not a result. "
    "Keep research findings attributed to their source; do not generalize them as universal facts. "
    "Use a question only when the explanation answers it with supplied facts. No forced questions. "
    "No invented numbers or facts, hashtags, rank labels, copyright claims, or production review notes. "
    "If essential evidence is missing, say 확인 필요 without inventing an answer. "
    "Do not return alternative drafts. Do not change original article titles. "
    "This feed_copy will be rendered EXACTLY by the image model; do not ask it to rewrite the text."
)

class FeedCopy(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    title: str = Field(min_length=1, max_length=80, description='독립적으로 쓴 한국어 피드 제목. 원제 발췌 금지. 사실·고유명사·수치·상태 유지.')
    description: str = Field(min_length=1, max_length=140, description='해당 기사 묶음에 근거한 핵심 설명. 제목 반복·근거 없는 사실·다른 묶음 수치 금지.')
