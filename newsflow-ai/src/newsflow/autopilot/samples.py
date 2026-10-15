"""Local sample RSS bytes; the URLs are provenance labels and are never fetched."""

from xml.sax.saxutils import escape

SAMPLE_URL = "https://example.com/newsflow/sample-rss"
SAMPLE_NAME = "NewsFlow 체험용 합성 뉴스 · 실제 보도 아님"
SAMPLE_TOPICS = (
    "[합성] 동네 도서관 독서 모임 운영 아이디어",
    "[합성] 야간 별자리 관측 수업 준비 사례",
    "[합성] 음식물 쓰레기 줄이기 생활 습관",
    "[합성] 재사용 포장으로 소포 보내기 실습",
    "[합성] 청소년 오케스트라 무대 기획 연습",
    "[합성] 반려 식물 물주기 달력 만들기",
    "[합성] 쉬운 글씨로 안내문 개선하기",
    "[합성] 안전한 자전거 정비 방법 배우기",
)


def sample_feed() -> bytes:
    entries = "".join(
        f"<item><title>{escape(title)}</title>"
        f"<link>https://example.com/newsflow/synthetic/{index}</link>"
        "<description>프로그램 사용 흐름을 연습하기 위해 만든 가상 기사입니다. 실제 사건이나 보도가 아닙니다.</description>"
        "</item>"
        for index, title in enumerate(SAMPLE_TOPICS, 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        f"<title>{SAMPLE_NAME}</title>{entries}</channel></rss>"
    ).encode()
