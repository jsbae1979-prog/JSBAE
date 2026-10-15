"""Reading-form normalization for Korean SAPI narration; affects spoken audio only.

Captions, review notes, narration estimates and the stored script keep the raw text.
Only the sentence handed to the Windows voice is rewritten here, so a listener hears
numbers, dates and acronyms the way a Korean news reader would say them. The function
is idempotent, never alters Hangul, imports nothing from the application and adds no
dependency. Every example below is checked in tests/test_speech_text.py.

Rules, in the order they run:

 0. Compatibility folding (NFKC) for non-Hangul characters only:
    "㎞" → "km", "％" → "%", "１２" → "12", "ℓ" → "L"; Hangul syllables and jamo stay as typed.
 1. Dotted acronyms: "U.S." → "유에스", "U.S.A." → "유에스에이".
 2. Dates with a four-digit year and a valid month/day:
    "2026-10-15" → "2026년 10월 15일", "2026.10.05" → "2026년 10월 5일", "2026/10/15" → "2026년 10월 15일".
    ISO date-times drop seconds and zone: "2026-10-15T14:30:00Z" → "2026년 10월 15일 14시 30분".
    "10/15", "15.10.2026", "1.2.3" and "02-1234-5678" are left alone.
 3. Clock times: "14:30" → "14시 30분", "오후 2:30" → "오후 2시 30분", "09:00" → "9시";
    "2:1" and "1:23:45" are left alone.
 4. Percent: "3.5%p" → "3.5퍼센트포인트", "3.5%" → "3.5퍼센트".
 5. Currency prefixes move after the number: "$100" → "100달러", "US$100" → "100달러",
    "€5.5" → "5.5유로", "£20" → "20파운드", "₩1,250,000" → "125만 원" (together with rule 7).
    A Korean scale word keeps its place: "$100만" → "100만 달러", "₩5만" → "5만 원", and
    "$5억 달러" → "5억 달러" (the written currency is not repeated).
 6. Units right after a number (optional space, not followed by a letter or digit):
    "12km" → "12킬로미터", "3 m" → "3미터", "5cm" → "5센티미터", "2mm" → "2밀리미터",
    "60kg" → "60킬로그램", "500g" → "500그램", "3t" → "3톤", "2L" → "2리터", "350mL" → "350밀리리터",
    "25°C" → "25도", "100km/h" → "시속 100킬로미터", "8GB" → "8기가바이트", "3.2GHz" → "3.2기가헤르츠",
    "10kWh" → "10킬로와트시", "50MW" → "50메가와트". "100m2" is left alone.
 7. Large numbers read in 만/억/조 groups, digits kept inside each group:
    "1,250,000" → "125만", "12,000" → "1만 2000", "10,000" → "1만", "123,456,789" → "1억 2345만 6789",
    "9,500" → "9500", "1,234.5" → "1234.5". Four-digit years, runs of 15 or more digits and digits
    glued to letters, "-", ".", "/" or ":" (phone numbers, versions, model codes) are left alone, and so
    are digit runs with a leading zero, which are identifiers rather than quantities ("005930" stock
    code, "01012345678" phone number, "06236" postcode).
 8. Ranges between numbers: "3~5" → "3에서 5", "3%∼5%" → "3퍼센트에서 5퍼센트"; never a hyphen.
 9. Upper-case acronyms of two to five letters are spelled with Korean letter names
    ("AI가" → "에이아이가", "KBS" → "케이비에스") unless pronounced as a word ("KOSPI" → "코스피",
    "NASA" → "나사", "KIA" → "기아", "KAIST" → "카이스트", "POSCO" → "포스코", "MERS" → "메르스",
    "AIDS" → "에이즈", "SARS" → "사스"); fixed tokens "5G" → "파이브지", "4K" → "포케이", "3D" → "쓰리디",
    "COVID-19" → "코비드 19", "K-POP" → "케이팝". Mixed case ("iPhone", "Google"), six or more letters ("ABCDEFG") and
    single-letter codes ("X100", "A5") stay; ordinary English words stay for SAPI to read.
10. Whitespace collapses to single spaces.
"""

from __future__ import annotations

import re
import unicodedata

MAX_SPOKEN_CHARS = 1000

LETTERS = {
    "A": "에이", "B": "비", "C": "시", "D": "디", "E": "이", "F": "에프", "G": "지", "H": "에이치", "I": "아이",
    "J": "제이", "K": "케이", "L": "엘", "M": "엠", "N": "엔", "O": "오", "P": "피", "Q": "큐", "R": "알",
    "S": "에스", "T": "티", "U": "유", "V": "브이", "W": "더블유", "X": "엑스", "Y": "와이", "Z": "제트",
}
PRONOUNCED = {
    "NASA": "나사", "FIFA": "피파", "NATO": "나토", "UNESCO": "유네스코", "OPEC": "오펙", "ASEAN": "아세안",
    "APEC": "에이펙", "KOSPI": "코스피", "KOSDAQ": "코스닥", "COVID": "코비드", "UEFA": "유에파",
    # Latin-letter names that Korean news reads as words, not letter by letter.
    "KIA": "기아", "KAIST": "카이스트", "POSCO": "포스코", "MERS": "메르스", "AIDS": "에이즈", "SARS": "사스",
}
FIXED_TOKENS = {"5G": "파이브지", "4K": "포케이", "3D": "쓰리디", "COVID-19": "코비드 19", "K-POP": "케이팝"}
CURRENCIES = {"$": "달러", "€": "유로", "£": "파운드", "₩": "원"}
UNITS = {
    "km/h": "킬로미터", "kWh": "킬로와트시", "GHz": "기가헤르츠", "MHz": "메가헤르츠", "MW": "메가와트",
    "GB": "기가바이트", "MB": "메가바이트", "TB": "테라바이트", "mL": "밀리리터", "ml": "밀리리터",
    "mm": "밀리미터", "cm": "센티미터", "km": "킬로미터", "kg": "킬로그램", "°C": "도", "℃": "도",
    "L": "리터", "t": "톤", "g": "그램", "m": "미터",
}

_HANGUL_RANGES = (
    (0x1100, 0x11FF), (0x3130, 0x318F), (0xA960, 0xA97F), (0xAC00, 0xD7AF), (0xD7B0, 0xD7FF), (0xFFA0, 0xFFDF),
)
# A number as typed: grouped with commas or plain digits, optional fraction, not a tail of another number.
_NUMBER = r"(?<![\d.,A-Za-z])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?"
_DOTTED = re.compile(r"(?<![A-Za-z])((?:[A-Z]\.){2,5})")
_DATETIME = re.compile(
    r"(?<![\d.A-Za-z])(\d{4})-(\d{2})-(\d{2})T([01]\d|2[0-3]):([0-5]\d)"
    r"(?::[0-5]\d(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?(?![\d:])"
)
_DATE = re.compile(r"(?<![\d.A-Za-z])(\d{4})([-./])(\d{1,2})\2(\d{1,2})(?!\d)")
_TIME = re.compile(r"(?<![\d:])([01]?\d|2[0-3]):([0-5]\d)(?![\d:])")
_PERCENT_POINT = re.compile(_NUMBER + r"\s?%p(?![A-Za-z])")
_PERCENT = re.compile(_NUMBER + r"\s?%")
_CURRENCY = re.compile(
    r"(?:US)?([$€£₩])\s?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?([만억조])?(?=(\s*(?:달러|유로|파운드|원))?)"
)
_UNIT = re.compile(
    _NUMBER + r"\s?(" + "|".join(re.escape(unit) for unit in UNITS) + r")(?![A-Za-z0-9])"
)
_GROUPED = re.compile(r"(?<![\d.,A-Za-z])(\d{1,3}(?:,\d{3})+)(\.\d+)?(?![\d,])(?=([가-힣]?))")
_PLAIN = re.compile(r"(?<![\d,\-./:A-Za-z])(\d{5,14})(?![\d,\-/:A-Za-z])(?!\.\d)(?=([가-힣]?))")
_RANGE = re.compile(r"(\d[가-힣]{0,6})\s*[~∼〜]\s*(?=\d)")
_FIXED = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(re.escape(t) for t in FIXED_TOKENS) + r")(?![A-Za-z0-9])")
_ACRONYM = re.compile(r"(?<![A-Za-z0-9])([A-Z]{2,5})(?![A-Za-z])")


def is_hangul(char: str) -> bool:
    code = ord(char)
    return any(low <= code <= high for low, high in _HANGUL_RANGES)


def _fold(text: str) -> str:
    """Rule 0: NFKC for everything except Hangul, which must never be recomposed or altered."""
    folded = []
    for char in text:
        if is_hangul(char):
            folded.append(char)
        elif char == "ℓ":
            folded.append("L")
        else:
            folded.append(unicodedata.normalize("NFKC", char))
    return "".join(folded)


def _spell(letters: str) -> str:
    return "".join(LETTERS[c] for c in letters if c in LETTERS)


def _datetime(match: re.Match) -> str:
    year, month, day, hour, minute = match.groups()
    if not (1 <= int(month) <= 12 and 1 <= int(day) <= 31):
        return match.group(0)
    return f"{year}년 {int(month)}월 {int(day)}일 {_clock(int(hour), int(minute))}"


def _date(match: re.Match) -> str:
    year, _separator, month, day = match.groups()
    if not (1 <= int(month) <= 12 and 1 <= int(day) <= 31):
        return match.group(0)
    return f"{year}년 {int(month)}월 {int(day)}일"


def _clock(hour: int, minute: int) -> str:
    return f"{hour}시" if minute == 0 else f"{hour}시 {minute}분"


def _time(match: re.Match) -> str:
    return _clock(int(match.group(1)), int(match.group(2)))


def _unit(match: re.Match) -> str:
    number, fraction, unit = match.group(1), match.group(2) or "", match.group(3)
    prefix = "시속 " if unit == "km/h" else ""
    return f"{prefix}{number}{fraction}{UNITS[unit]}"


def read_number(digits: str) -> str:
    """Korean grouping of an integer written in digits: 1250000 → '125만', 12000 → '1만 2000'."""
    value = int(digits)
    if value < 10_000:
        return str(value)
    parts = []
    for unit, size in (("조", 10**12), ("억", 10**8), ("만", 10**4)):
        quotient, value = divmod(value, size)
        if quotient:
            parts.append(f"{quotient}{unit}")
    if value:
        parts.append(str(value))
    return " ".join(parts)


def _currency(match: re.Match) -> str:
    """'$100' → '100달러'; with a Korean scale word '$100만' → '100만 달러' (never '100달러만')."""
    symbol, number, fraction, scale, written = match.groups()
    amount = f"{number}{fraction or ''}"
    if not scale:
        return f"{amount}{CURRENCIES[symbol]}"
    # '$5억 달러': the currency is already written after the scale word, so do not repeat it.
    return f"{amount}{scale}" if written else f"{amount}{scale} {CURRENCIES[symbol]}"


def _large(match: re.Match) -> str:
    groups = match.groups()
    digits = groups[0].replace(",", "")
    fraction = groups[1] if len(groups) == 3 else ""
    following = groups[-1]
    if len(digits) >= 15:
        return match.group(0)
    if len(digits) > 1 and digits.startswith("0"):
        # A leading zero marks an identifier (stock code 005930, phone 010…, postcode 06236), never a quantity.
        return match.group(0)
    if fraction:
        return digits + fraction
    reading = read_number(digits)
    # "125만 원" / "1억 2345만 6789명": a space only after a 만/억/조 word, never inside Hangul.
    if following and reading[-1] in "만억조":
        reading += " "
    return reading


def _acronym(match: re.Match) -> str:
    word = match.group(1)
    return PRONOUNCED.get(word) or _spell(word)


def normalize_for_speech(text: str) -> str:
    """Spoken form of ``text`` for a Korean SAPI voice; idempotent and Hangul-preserving."""
    spoken = _fold(text)
    spoken = _DOTTED.sub(lambda m: _spell(m.group(1)), spoken)
    spoken = _DATETIME.sub(_datetime, spoken)
    spoken = _DATE.sub(_date, spoken)
    spoken = _TIME.sub(_time, spoken)
    spoken = _PERCENT_POINT.sub(lambda m: f"{m.group(1)}{m.group(2) or ''}퍼센트포인트", spoken)
    spoken = _PERCENT.sub(lambda m: f"{m.group(1)}{m.group(2) or ''}퍼센트", spoken)
    spoken = _CURRENCY.sub(_currency, spoken)
    spoken = _UNIT.sub(_unit, spoken)
    spoken = _GROUPED.sub(_large, spoken)
    spoken = _PLAIN.sub(_large, spoken)
    spoken = _RANGE.sub(r"\1에서 ", spoken)
    spoken = _FIXED.sub(lambda m: FIXED_TOKENS[m.group(1)], spoken)
    spoken = _ACRONYM.sub(_acronym, spoken)
    return " ".join(spoken.split())


__all__ = ["MAX_SPOKEN_CHARS", "is_hangul", "normalize_for_speech", "read_number"]
