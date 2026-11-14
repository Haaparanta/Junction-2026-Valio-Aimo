"""The gateway's own numbers and dates, written for messages in Finnish and English (Europe/Helsinki).

No time-zone database is needed (slim images may lack one): Finland follows the EU summer-time rule, UTC+3 from
the last Sunday of March to the last Sunday of October (switching at 01:00 UTC) and UTC+2 otherwise.
"""

from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
EET = timezone(timedelta(hours=2))
EEST = timezone(timedelta(hours=3))
WEEKDAY_FI = ["ma", "ti", "ke", "to", "pe", "la", "su"]
WEEKDAY_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
UNIT_FI = {"L": "l", "KG": "kg", "PCS": "kpl"}
UNIT_EN = {"L": "L", "KG": "kg", "PCS": "pc"}


def money(d: Decimal) -> str:
    """Money as a decimal string with two places, rounded half-up (F-06)."""
    return str(d.quantize(CENT, rounding=ROUND_HALF_UP))


def num(d: Decimal) -> str:
    """A quantity without trailing zeros or an exponent: 21.0 -> '21', 1E+3 -> '1000', 1.250 -> '1.25'."""
    return format(d.normalize(), "f")


def fi(number: str) -> str:
    """A number for Finnish text: decimal comma (1010.00 -> 1010,00)."""
    return number.replace(".", ",")


def _last_sunday(year: int, month: int) -> date:
    d = date(year, month, 31)  # March and October both have 31 days
    return d - timedelta(days=(d.weekday() + 1) % 7)


def helsinki_at(d: date, hhmm: str) -> datetime:
    """A Helsinki wall-clock time on a date. Cut-offs fall in the afternoon, never in the 03:00-04:00 switch."""
    hour, minute = (int(x) for x in hhmm.split(":"))
    tz = EEST if _last_sunday(d.year, 3) <= d < _last_sunday(d.year, 10) else EET
    return datetime.combine(d, time(hour, minute), tz)


def instant(iso: str) -> datetime:
    """An ISO time such as the AS_OF clock; one without an offset is Helsinki wall-clock time."""
    dt = datetime.fromisoformat(iso)
    return dt if dt.tzinfo else helsinki_at(dt.date(), f"{dt.hour}:{dt.minute}").replace(second=dt.second)


def to_helsinki(dt: datetime) -> datetime:
    utc = dt.astimezone(UTC)
    start = datetime.combine(_last_sunday(utc.year, 3), time(1), UTC)
    end = datetime.combine(_last_sunday(utc.year, 10), time(1), UTC)
    return utc.astimezone(EEST if start <= utc < end else EET)


def day_fi(d: date) -> str:
    return f"{WEEKDAY_FI[d.weekday()]} {d.day}.{d.month}."  # ma 16.11.


def day_en(d: date) -> str:
    return f"{WEEKDAY_EN[d.weekday()]} {d.day}.{d.month}"  # Mon 16.11


def clock_fi(dt: datetime) -> str:
    h = to_helsinki(dt)
    return f"klo {h.hour}.{h.minute:02d}"  # klo 17.00


def clock_en(dt: datetime) -> str:
    h = to_helsinki(dt)
    return f"{h.hour}:{h.minute:02d}"  # 17:00


def at_fi(dt: datetime) -> str:
    return f"{day_fi(to_helsinki(dt).date())} {clock_fi(dt)}"  # su 15.11. klo 17.00


def at_en(dt: datetime) -> str:
    return f"{day_en(to_helsinki(dt).date())} {clock_en(dt)}"  # Sun 15.11 17:00


def quoted(text: str, limit: int = 80) -> str:
    """Product names and need text are data: one line, bounded and in quotes, so they never read as instructions."""
    s = " ".join(str(text).split()).replace('"', "'")
    if len(s) > limit:
        s = s[: limit - 1] + "…"
    return f'"{s}"'


def ids_fi(ids: list[int]) -> str:
    """1 -> '1'; [2, 4] -> '2 ja 4'; [1, 2, 3] -> '1, 2 ja 3'."""
    parts = [str(i) for i in ids]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " ja " + parts[-1]


def ids_en(ids: list[int]) -> str:
    parts = [str(i) for i in ids]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
