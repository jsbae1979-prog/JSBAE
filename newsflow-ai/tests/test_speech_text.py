"""Reading-form normalization: every documented rule, negatives, idempotency and Hangul preservation."""

from __future__ import annotations

import pytest

from newsflow.video.speech_text import MAX_SPOKEN_CHARS, is_hangul, normalize_for_speech, read_number
from newsflow.video.tts import PREVIEW_TEXT

# Documented spoken form of the fixed preview sentence (settings → 음성과 자막 shows both).
PREVIEW_SPOKEN = (
    "안녕하세요. 뉴스플로 음성 미리 듣기입니다. 2026년 10월 15일 14시 30분 기준 코스피는 3.5퍼센트 올랐고, "
    "에이아이 기업 매출은 125만 달러입니다."
)

POSITIVE = [
    # 0. compatibility folding, Hangul untouched
    ("㎞ ％ １２", "km % 12"), ("２ℓ", "2리터"), ("가나다 ㅋㅋ", "가나다 ㅋㅋ"),
    # 1. dotted acronyms
    ("U.S.", "유에스"), ("U.S.A.", "유에스에이"),
    # 2. dates and ISO date-times
    ("2026-10-15", "2026년 10월 15일"), ("2026.10.05", "2026년 10월 5일"), ("2026/10/15", "2026년 10월 15일"),
    ("2026-10-15T14:30:00Z", "2026년 10월 15일 14시 30분"), ("2026-10-15T09:00+09:00", "2026년 10월 15일 9시"),
    ("2026-10-15T14:30:15.5-05:00", "2026년 10월 15일 14시 30분"),
    # 3. clock times
    ("14:30", "14시 30분"), ("오후 2:30", "오후 2시 30분"), ("09:00", "9시"), ("23:59", "23시 59분"),
    # 4. percent and percent points
    ("3.5%p", "3.5퍼센트포인트"), ("3.5%", "3.5퍼센트"), ("12 %", "12퍼센트"), ("0.5%p 상승", "0.5퍼센트포인트 상승"),
    # 5. currency prefixes become suffixes
    ("$100", "100달러"), ("US$100", "100달러"), ("€5.5", "5.5유로"), ("£20", "20파운드"),
    ("₩1,250,000", "125만 원"), ("$1,250,000입니다", "125만 달러입니다"), ("$ 42", "42달러"),
    ("$100만", "100만 달러"), ("₩5만", "5만 원"), ("$5억 달러", "5억 달러"), ("$1.5조", "1.5조 달러"),
    # 6. units
    ("12km", "12킬로미터"), ("3 m", "3미터"), ("5cm", "5센티미터"), ("2mm", "2밀리미터"), ("60kg", "60킬로그램"),
    ("500g", "500그램"), ("3t", "3톤"), ("2L", "2리터"), ("350mL", "350밀리리터"), ("200ml", "200밀리리터"),
    ("25°C", "25도"), ("25℃", "25도"), ("100km/h", "시속 100킬로미터"), ("8GB", "8기가바이트"),
    ("3.2GHz", "3.2기가헤르츠"), ("10kWh", "10킬로와트시"), ("50MW", "50메가와트"),
    ("512MB 2TB 1MHz", "512메가바이트 2테라바이트 1메가헤르츠"), ("1,250km", "1250킬로미터"),
    # 7. large numbers
    ("1,250,000", "125만"), ("12,000", "1만 2000"), ("10,000", "1만"), ("123,456,789", "1억 2345만 6789"),
    ("9,500", "9500"), ("1,234.5", "1234.5"), ("12345", "1만 2345"), ("1,250,000명", "125만 명"),
    ("1234567890123", "1조 2345억 6789만 123"), ("100,000,000원", "1억 원"), ("만약 12,000원이면", "만약 1만 2000원이면"),
    ("매출은 12345.", "매출은 1만 2345."),
    # 8. ranges
    ("3~5", "3에서 5"), ("3∼5", "3에서 5"), ("3 ~ 5", "3에서 5"), ("3%∼5%", "3퍼센트에서 5퍼센트"),
    # 9. acronyms, pronounced words and fixed tokens
    ("AI가", "에이아이가"), ("KBS", "케이비에스"), ("KOSPI는", "코스피는"), ("NASA", "나사"), ("USA", "유에스에이"),
    ("5G", "파이브지"), ("4K", "포케이"), ("3D", "쓰리디"), ("COVID-19", "코비드 19"), ("한국IT", "한국아이티"),
    ("KIA 타이거즈", "기아 타이거즈"), ("KAIST", "카이스트"), ("POSCO", "포스코"), ("MERS", "메르스"),
    ("AIDS", "에이즈"), ("SARS", "사스"), ("K-POP 공연", "케이팝 공연"),
    # 10. whitespace
    ("두  칸\n줄바꿈", "두 칸 줄바꿈"),
    # the preview sentence end to end
    (PREVIEW_TEXT, PREVIEW_SPOKEN),
]
NEGATIVE = [
    "10/15", "2:1", "1.2.3", "02-1234-5678", "iPhone 15 Pro", "ABCDEFG", "X100", "A5", "Google", "2026",
    "15.10.2026", "1:23:45", "100m2", "123456789012345", "2026-13-45", "v1.10.2", "뉴스 영상",
    # leading-zero identifiers: stock codes, phone numbers, postcodes
    "삼성전자(005930)", "000660", "01012345678", "우편번호 06236",
]


@pytest.mark.parametrize("source,expected", POSITIVE)
def test_documented_rules(source, expected):
    assert normalize_for_speech(source) == expected


@pytest.mark.parametrize("source", NEGATIVE)
def test_left_alone_except_folding(source):
    assert normalize_for_speech(source) == source


@pytest.mark.parametrize("source,expected", POSITIVE)
def test_idempotent(source, expected):
    assert normalize_for_speech(expected) == expected
    assert normalize_for_speech(normalize_for_speech(source)) == normalize_for_speech(source)


def test_preview_text_spoken_form_is_documented():
    assert PREVIEW_TEXT.startswith("안녕하세요")
    assert normalize_for_speech(PREVIEW_TEXT) == PREVIEW_SPOKEN


@pytest.mark.parametrize("text", [
    "시청이 2026년까지 자전거 도로 12km를 늘린다고 밝혔습니다.", "ㄱㄴㄷ ㅏㅑ 한글", "만약 12,000원이면 KOSPI 3.5%p",
    "예산 500억 원이 투입됩니다.", "가 ㄱ ﾡ 가", "AI와 U.S. 달러 $5~$7 사이",
])
def test_hangul_is_preserved_in_order(text):
    source = [c for c in text if is_hangul(c)]
    spoken = iter(c for c in normalize_for_speech(text) if is_hangul(c))
    assert all(char in spoken for char in source)  # every input Hangul char survives, in order


def test_read_number_groups():
    assert read_number("1250000") == "125만" and read_number("12000") == "1만 2000" and read_number("10000") == "1만"
    assert read_number("123456789") == "1억 2345만 6789" and read_number("9500") == "9500"
    assert read_number("10000000000000") == "10조"


def test_length_bound_for_ordinary_scripts():
    narration = "시청이 2026-10-15 14:30에 자전거 도로 12km와 예산 1,250,000원을 발표했습니다. " * 5
    assert len(narration) <= 400 and len(normalize_for_speech(narration)) <= MAX_SPOKEN_CHARS
    assert len(normalize_for_speech("가" * 400)) == 400
    # Letter spelling can exceed the limit; WindowsTTS._speak rejects that instead of truncating.
    assert len(normalize_for_speech(("WWWWW " * 66).strip())) > MAX_SPOKEN_CHARS
