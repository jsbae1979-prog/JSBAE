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


def news_hashtags(title, body, category=None):
    """News taxonomy is separate from the existing YouTube numeric categories."""
    import re
    text = str(title) + ' ' + str(body)
    groups = [('정치', r'정치|의원|대통령|선거|parliament|minister|election'),
              ('경제', r'금리|경제|주식|물가|은행|금융|economy|interest rate|inflation'),
              ('국제', r'국제|외교|해외|전쟁|분쟁|world|war'),
              ('과학기술', r'과학|기술|반도체|인공지능|technology|science'),
              ('사회', r'사건|사고|공격|시위|교육|attack|protest'),
              ('문화', r'문화|영화|공연|culture|cinema'), ('스포츠', r'스포츠|축구|야구|sport')]
    label = category if category in {g[0] for g in groups} else next((tag for tag,pattern in groups if re.search(pattern,text,re.I)), '시사')
    regions = [('호주',r'호주|오스트레일리아|australia'),('미국',r'미국|워싱턴|미시간|united states|michigan'),
               ('프랑스',r'프랑스|파리|france|paris'),('영국',r'영국|런던|britain|london'),
               ('일본',r'일본|도쿄|japan'),('한국',r'한국|서울|국내|한국은행|korea')]
    region = next((tag for tag,pattern in regions if re.search(pattern,text,re.I)), '세계')
    return ' '.join(dict.fromkeys(['#뉴스요약','#'+label,'#'+region]))
