"""Offline YouTube video-category choices, separate from RSS/news taxonomy.

YouTube resource contract: https://developers.google.com/youtube/v3/docs/videoCategories
These standard category IDs are local choices, not a live region/assignable lookup.
No API request occurs when rendering the form. YouTube remains authoritative.
"""

YOUTUBE_CATEGORIES = {
    "1": "영화·애니메이션", "2": "자동차", "10": "음악", "15": "반려동물·동물",
    "17": "스포츠", "19": "여행·이벤트", "20": "게임", "22": "인물·블로그",
    "23": "코미디", "24": "엔터테인먼트", "25": "뉴스·정치", "26": "노하우·스타일",
    "27": "교육", "28": "과학·기술",
}


def valid_category(value: object) -> bool:
    return isinstance(value, str) and value in YOUTUBE_CATEGORIES
