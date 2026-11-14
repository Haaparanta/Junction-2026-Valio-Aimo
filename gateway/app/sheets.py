"""Excel and CSV order lists as rows (docs/basket-plan.md M25.3, docs/briefs/basket-import-clickable.md section 3).

read_sheet() turns an uploaded .xlsx or .csv into SheetRows: what each row asks for, as read. It never matches or
prices; match.py and the import pipeline do that. One bad row never fails the file: the row carries its problems and
the other rows still come back. Only a file that cannot be read at all raises SheetError: too large (413), a format
this module does not read (415), or empty, damaged, a zip bomb or more than MAX_ROWS rows (422).

Cell values are data, never instructions, and no problem message quotes them.
"""

import codecs
import csv
import io
import re
import unicodedata
import warnings
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import PurePath
from typing import Literal

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils.datetime import from_excel
from openpyxl.worksheet.datavalidation import DataValidation

from .contract import Msg, Unit

MAX_BYTES = 1_000_000
MAX_ROWS = 200  # product rows; more refuses the file
MAX_UNZIPPED = 20_000_000  # an .xlsx larger than this unpacked is refused before openpyxl opens it
MAX_ZIP_ENTRIES = 500  # a workbook has a dozen parts; thousands are a zip bomb
MAX_SCAN_ROWS = 5 * MAX_ROWS  # rows with values read before giving up on a sheet
MAX_COLUMNS = 50  # columns further right are ignored
MAX_CELL = 200
MAX_RAW = 300
MAX_AMOUNT = Decimal(1_000_000)  # the contract's upper bound for an amount
HEADER_SEARCH = 10  # the header may sit below a title, within the first rows that have values
GTIN_LENGTHS = (8, 12, 13, 14)

Cell = str | int | float | bool | datetime | date | time | None  # what openpyxl or the csv module gives
Field = Literal["product_id", "gtin", "name", "amount", "unit", "need_date", "note"]


class SheetError(Exception):
    """The whole file is refused. status_code is the HTTP answer (413, 415 or 422); code names the reason."""

    def __init__(self, status_code: Literal[413, 415, 422], code: str, fi: str, en: str) -> None:
        super().__init__(en)
        self.status_code = status_code
        self.code = code
        self.message = Msg(fi=fi, en=en)


@dataclass(frozen=True)
class SheetRow:
    row_number: int  # the physical row, 1-based; the header row counts
    product_id: str  # "" when the row has none
    gtin: str  # digits only, or ""
    name: str
    amount: Decimal | None  # None when missing or unreadable (the row has a problem then)
    unit: Unit | None
    need_date: str | None  # YYYY-MM-DD; None when missing, and the pipeline uses the next deliverable date
    note: str
    raw_text: str  # the row's cells joined with " | ", at most MAX_RAW characters
    problems: list[Msg] = field(default_factory=list)


_MB = MAX_BYTES // 1_000_000
_ERRORS: dict[str, tuple[Literal[413, 415, 422], str, str]] = {
    "too_large": (
        413,
        f"Tiedosto on liian suuri: enintään {_MB} Mt. Jaa lista pienempiin tiedostoihin.",
        f"The file is too large: at most {_MB} MB. Split the list into smaller files.",
    ),
    "xls": (
        415,
        "Vanhaa .xls-tiedostoa tai salasanalla suojattua työkirjaa ei voi lukea. "
        "Tallenna se muodossa .xlsx tai .csv ilman salasanaa.",
        "An old .xls file or a password-protected workbook cannot be read. "
        "Save it as .xlsx or .csv without a password.",
    ),
    "not_a_workbook": (
        415,
        "Tiedosto ei ole Excel-työkirja. Tallenna se muodossa .xlsx tai .csv.",
        "The file is not an Excel workbook. Save it as .xlsx or .csv.",
    ),
    "unsupported": (
        415,
        "Tätä tiedostotyyppiä ei voi lukea. Lähetä .xlsx- tai .csv-tiedosto.",
        "This type of file cannot be read. Send an .xlsx or .csv file.",
    ),
    "empty": (422, "Tiedosto on tyhjä.", "The file is empty."),
    "damaged": (
        422,
        "Excel-tiedostoa ei voi lukea; se voi olla vioittunut. Tallenna se uudelleen muodossa .xlsx tai .csv.",
        "The Excel file cannot be read; it may be damaged. Save it again as .xlsx or .csv.",
    ),
    "zip_bomb": (
        422,
        "Työkirja on purettuna liian suuri tai siinä on liikaa osia.",
        "The workbook is too large when unpacked, or has too many parts.",
    ),
    "encoding": (
        422,
        "Tiedoston merkistöä ei tunnistettu. Tallenna CSV-tiedosto UTF-8-muodossa.",
        "The file's text encoding was not recognised. Save the CSV as UTF-8.",
    ),
    "bad_csv": (
        422,
        "CSV-tiedostoa ei voi lukea. Tarkista lainausmerkit.",
        "The CSV file cannot be read. Check its quotation marks.",
    ),
    "too_many_rows": (
        422,
        f"Listassa on yli {MAX_ROWS} tuoteriviä. Jaa se useampaan tiedostoon.",
        f"The list has more than {MAX_ROWS} product rows. Split it into several files.",
    ),
    "no_rows": (
        422,
        "Tiedostosta ei löytynyt tuoterivejä. Anna sarakkeille otsikot, esimerkiksi tuotenumero, tuote, määrä, "
        "yksikkö ja toimituspäivä.",
        "No product rows were found. Give the columns headers such as product id, name, quantity, unit and "
        "delivery date.",
    ),
}

P_AMOUNT = Msg(fi="Määrä ei ole luku.", en="The amount is not a number.")
P_AMOUNT_ZERO = Msg(fi="Määrän pitää olla nollaa suurempi.", en="The amount must be more than zero.")
P_AMOUNT_BIG = Msg(fi="Määrä on liian suuri (enintään 1 000 000).", en="The amount is too large (at most 1,000,000).")
P_AMOUNT_UNCLEAR = Msg(
    fi="Määrä on epäselvä: tuhat vai yksi? Kirjoita esimerkiksi 1000 tai 1,5.",
    en="The amount is unclear: a thousand or one? Write it as, for example, 1000 or 1,5.",
)
P_UNIT = Msg(fi="Yksikön pitää olla l, kg tai kpl.", en="The unit must be L, KG or PCS.")
P_UNIT_CLASH = Msg(fi="Määrässä ja yksikössä on eri yksiköt.", en="The amount and the unit give different units.")
P_DATE = Msg(
    fi="Toimituspäivää ei voi lukea. Kirjoita se muodossa 16.11.2026.",
    en="The delivery date cannot be read. Write it as 16.11.2026 or 2026-11-16.",
)
P_GTIN = Msg(fi="GTIN-koodissa saa olla vain numeroita.", en="A GTIN may contain digits only.")
P_CODE_EXP = Msg(
    fi="Excel on muuttanut koodin muotoon 6,4E+12. Muotoile sarake tekstiksi ja kirjoita koodi uudelleen.",
    en="Excel turned the code into a number like 6.4E+12. Format the column as text and type the code again.",
)
P_CUT = Msg(
    fi=f"Solussa oli yli {MAX_CELL} merkkiä, joten se katkaistiin.",
    en=f"A cell was longer than {MAX_CELL} characters, so it was cut.",
)
P_NO_ITEM = Msg(
    fi="Rivillä ei ole tuotenumeroa, GTIN-koodia eikä tuotteen nimeä.",
    en="The row has no product id, GTIN or product name.",
)

_HEADER_NAMES: dict[Field, tuple[str, ...]] = {
    "product_id": ("product id", "product_id", "tuotenumero", "tuotenro", "tuote nro", "tuote-nro"),
    "gtin": ("gtin", "ean", "ean13", "ean-koodi"),
    "name": ("name", "tuote", "nimi", "product", "tuotenimi"),
    "amount": ("quantity", "qty", "määrä", "maara", "amount", "lkm"),
    "unit": ("unit", "yksikkö", "yksikko", "yks"),
    "need_date": ("delivery date", "toimituspäivä", "toimituspaiva", "date", "pvm"),
    "note": ("note", "lisätieto", "lisatieto", "huom"),
}
_UNITS: dict[str, Unit] = {
    **dict.fromkeys(("l", "ltr", "litra", "litraa", "litre", "litres", "liter", "liters"), "L"),
    **dict.fromkeys(("kg", "kilo", "kiloa", "kilogramma", "kilogrammaa"), "KG"),
    **dict.fromkeys(("pcs", "pc", "kpl", "st", "stk", "ea", "kappale", "kappaletta"), "PCS"),
}
_MAGIC_ZIP = (b"PK\x03\x04", b"PK\x05\x06")
_MAGIC_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # old .xls, and also any password-protected .xlsx
_MAGIC_BINARY = (b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"%PDF", b"RIFF", b"\x1f\x8b", b"7z\xbc\xaf", b"Rar!")
_UTF16_BOMS = (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)
_TEXT_EXTENSIONS = (".csv", ".txt", ".tsv")
_CSV_TYPES = ("text/csv", "application/csv", "text/tab-separated-values")
_TEXT_TYPES = (*_CSV_TYPES, "text/plain", "application/vnd.ms-excel")  # Windows browsers send the last for .csv
_DIGITS = re.compile(r"[0-9]+")
_SCIENTIFIC = re.compile(r"[0-9]+(?:[.,][0-9]+)?[eE]\+?[0-9]+")
_GROUP_SPACE = re.compile(r"(?<=[0-9])[\s']+(?=[0-9])")  # 1 000, 1 000 with a no-break space, 1'000
_AMOUNT = re.compile(r"([-+−]?)([0-9][0-9.,]*)\s*([^\W\d_][^\d]*)?")
_THOUSANDS = re.compile(r"[0-9]{1,3}(?:[.,][0-9]{3})+")
_UNCLEAR = re.compile(r"[1-9][0-9]{0,2}[.,][0-9]{3}")  # 1.000 or 1,500: a thousand or one?
_ISO_DATE = re.compile(r"([0-9]{4})-([0-9]{1,2})-([0-9]{1,2})(?:[T ][0-9]{1,2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]+)?)?)?")
_FI_DATE = re.compile(r"([0-9]{1,2})\.([0-9]{1,2})\.([0-9]{4}|[0-9]{2})(?:\s+[0-9]{1,2}[:.][0-9]{2}(?:[:.][0-9]{2})?)?")
_HEADER_EXTRA = re.compile(r"(.+?)\s*(?:\((.*)\)|\[(.*)\]|\s(\S+))")  # 'määrä (kg)', 'määrä kg', 'pvm (pp.kk.vvvv)'


def _header_key(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("­", "").replace("​", "").replace("_", " ")
    return " ".join(text.casefold().split()).strip(" :.*!?")


_ALIASES: dict[str, Field] = {_header_key(n): f for f, names in _HEADER_NAMES.items() for n in names}


def read_sheet(filename: str, content_type: str, data: bytes) -> list[SheetRow]:
    """The product rows of an uploaded .xlsx or .csv, in sheet order. Raises SheetError for a file it cannot read."""
    if len(data) > MAX_BYTES:
        raise _error("too_large")
    if not data.lstrip(codecs.BOM_UTF8 + codecs.BOM_UTF16_LE).strip(b" \t\r\n\x00"):
        raise _error("empty")
    extension = PurePath(filename or "").suffix.casefold()
    media_type = (content_type or "").split(";")[0].strip().casefold()
    if data.startswith(_MAGIC_OLE) or extension == ".xls":
        raise _error("xls")
    if data.startswith(_MAGIC_ZIP):
        table = _xlsx_cells(data)
    elif data.startswith(_MAGIC_BINARY) or (b"\x00" in data[:4096] and not data.startswith(_UTF16_BOMS)):
        raise _error("unsupported")
    elif extension in (".xlsx", ".xlsm"):
        raise _error("damaged")  # named a workbook, but not a zip
    elif extension in _TEXT_EXTENSIONS or media_type in _CSV_TYPES or (not extension and media_type in _TEXT_TYPES):
        table = _csv_cells(data)
    else:
        raise _error("unsupported")
    return _sheet_rows(table)


# ---- reading the cells ----------------------------------------------------------------------------------------


def _xlsx_cells(data: bytes) -> list[tuple[int, list[Cell]]]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            parts = archive.infolist()
    except (zipfile.BadZipFile, EOFError, ValueError) as exc:
        raise _error("damaged") from exc
    # ZipFile never unpacks more than an entry's declared size, so checking the declared sizes bounds the memory.
    # The XML inside is parsed by expat, which limits entity expansion itself.
    if len(parts) > MAX_ZIP_ENTRIES or sum(p.file_size for p in parts) > MAX_UNZIPPED:
        raise _error("zip_bomb")
    if not any(p.filename.startswith("xl/") for p in parts):
        raise _error("not_a_workbook")  # an .ods, .docx or other zip
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # openpyxl warns about styles and extensions it skips
            book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            try:
                return _sheet_cells(book)
            finally:
                book.close()
    except SheetError:
        raise
    except Exception as exc:  # openpyxl raises many kinds of errors on a damaged workbook
        raise _error("damaged") from exc


def _sheet_cells(book) -> list[tuple[int, list[Cell]]]:
    """The active sheet's rows that have values, with their physical row numbers."""
    sheet = book.active
    if not hasattr(sheet, "iter_rows"):  # a chart sheet is active
        sheet = book.worksheets[0] if book.worksheets else None
    if sheet is None:
        return []
    sheet.reset_dimensions()  # some writers store a wrong used range; read every row that is there
    rows: list[tuple[int, list[Cell]]] = []
    for number, values in enumerate(sheet.iter_rows(values_only=True), start=1):
        cells = list(values[:MAX_COLUMNS])
        if any(_text(c) for c in cells):
            rows.append((number, cells))
            if len(rows) > MAX_SCAN_ROWS:
                raise _error("too_many_rows")
    return rows


def _csv_cells(data: bytes) -> list[tuple[int, list[Cell]]]:
    text = _decode(data)
    lines = text.splitlines()
    sep_line = re.fullmatch(r'"?sep=(.)"?', lines[0].strip(), re.IGNORECASE) if lines else None
    rows: list[tuple[int, list[Cell]]] = []
    try:
        delimiter = sep_line.group(1) if sep_line else _delimiter([ln for ln in lines[:50] if ln.strip()][:5])
        records = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
        for number, record in enumerate(records, start=0 if sep_line else 1):  # Excel hides a sep= line
            cells: list[Cell] = list(record[:MAX_COLUMNS])
            if number and any(_text(c) for c in cells):
                rows.append((number, cells))
                if len(rows) > MAX_SCAN_ROWS:
                    raise _error("too_many_rows")
    except csv.Error as exc:  # a stray quotation mark, or a field over the csv module's size limit
        raise _error("bad_csv") from exc
    return rows


def _decode(data: bytes) -> str:
    """UTF-16 with a BOM (Excel's 'Unicode text'), UTF-8 with or without a BOM, else cp1252 (Finnish Excel)."""
    encodings = ["utf-16"] if data.startswith(_UTF16_BOMS) else ["utf-8-sig", "cp1252"]
    for encoding in encodings:
        try:
            return data.decode(encoding).removeprefix("ï»¿")  # a UTF-8 BOM on a cp1252 file
        except UnicodeDecodeError:
            continue
    raise _error("encoding")


def _delimiter(sample: list[str]) -> str:
    """Tab, ';' or ',': the one that splits every sampled line into the most fields; ';' when none splits them."""
    best, most = ";", 1
    for candidate in ("\t", ";", ","):
        fields = min((len(r) for r in csv.reader(sample, delimiter=candidate)), default=1)
        if fields > most:
            best, most = candidate, fields
    return best


# ---- cells to rows ---------------------------------------------------------------------------------------------


def _sheet_rows(table: list[tuple[int, list[Cell]]]) -> list[SheetRow]:
    if not table:
        raise _error("empty")
    header = _find_header(table)
    if header is None:
        rows = [_row_by_order(number, cells) for number, cells in table]
    else:
        columns, default_unit = _columns(table[header][1])
        data = table[header + 1 :]
        if "product_id" not in columns:
            _add_id_column(columns, data)
        rows = [_row_by_columns(number, cells, columns, default_unit) for number, cells in data]
    found = [r for r in rows if r is not None]
    if len(found) > MAX_ROWS:
        raise _error("too_many_rows")
    if not any(r.product_id or r.gtin or r.name for r in found):
        raise _error("no_rows")
    return found


def _find_header(table: list[tuple[int, list[Cell]]]) -> int | None:
    """The header row among the first rows: known column names and nothing that looks like data. Below a title it
    needs two known names, so that a data row such as 'voi | huom' is never taken for one."""
    for i, (_, cells) in enumerate(table[:HEADER_SEARCH]):
        known = sum(1 for c in cells if _header_field(c)[0])
        looks_like_data = any((c is not None and not isinstance(c, str)) or _is_data_text(c) for c in cells)
        if known and not looks_like_data and (known >= 2 or i == 0):
            return i
    return None


def _is_data_text(cell: Cell) -> bool:
    return isinstance(cell, str) and _header_field(cell)[0] is None and any(ch.isdigit() for ch in cell)


def _header_field(cell: Cell) -> tuple[Field | None, Unit | None]:
    """The field a header names, and a unit it gives the amount column ('määrä (kg)')."""
    if not isinstance(cell, str):
        return None, None
    key = _header_key(cell)
    if key in _ALIASES:
        return _ALIASES[key], None
    extra = _HEADER_EXTRA.fullmatch(key)
    if extra is None or extra.group(1) not in _ALIASES:
        return None, None
    found = _ALIASES[extra.group(1)]
    detail = next(g for g in extra.groups()[1:] if g is not None).strip(" .")
    if found == "amount":
        return found, _UNITS.get(detail)
    return (found, None) if extra.group(4) is None else (None, None)  # only a note in brackets on other headers


def _columns(header: list[Cell]) -> tuple[dict[Field, int], Unit | None]:
    columns: dict[Field, int] = {}
    default_unit: Unit | None = None
    for i, cell in enumerate(header):
        found, unit = _header_field(cell)
        if found and found not in columns:  # the first column with a name wins
            columns[found] = i
            default_unit = unit if found == "amount" else default_unit
    return columns, default_unit


def _add_id_column(columns: dict[Field, int], data: list[tuple[int, list[Cell]]]) -> None:
    """Without a product id header, an unnamed column whose values are mostly six-digit numbers holds the ids."""
    width = max((len(cells) for _, cells in data), default=0)
    for i in range(width):
        if i in columns.values():
            continue
        values = [_code(cells[i], []) for _, cells in data if i < len(cells) and _text(cells[i])]
        if values and 2 * sum(_code_kind(v) == "id" for v in values) > len(values):
            columns["product_id"] = i
            return


def _row_by_columns(
    number: int, cells: list[Cell], columns: dict[Field, int], default_unit: Unit | None
) -> SheetRow | None:
    def cell(name: Field) -> Cell:
        i = columns.get(name)
        return cells[i] if i is not None and i < len(cells) else None

    return _row(
        number,
        cells,
        [cell(f) for f in ("product_id", "gtin", "name", "amount", "unit", "need_date", "note")],
        default_unit,
    )


def _row_by_order(number: int, cells: list[Cell]) -> SheetRow | None:
    """No header: id or name, amount, unit, date, note. A six-digit first cell is an id, 8, 12, 13 or 14 digits a
    GTIN, anything else a name; an id (or an empty first cell) followed by text is id, name, amount... as in the
    template."""
    first, rest = (cells[0], list(cells[1:])) if cells else (None, [])
    kind = _code_kind(_code(first, []))
    named = None
    if (kind or not _text(first)) and rest and isinstance(rest[0], str) and _text(rest[0]):
        if not _AMOUNT.fullmatch(_GROUP_SPACE.sub("", _text(rest[0]))):
            named, rest = rest[0], rest[1:]
    product_id = first if kind == "id" else None
    gtin = first if kind == "gtin" else None
    name = named if named is not None or kind else first
    amount, unit, need_date, note = (rest + [None] * 4)[:4]
    return _row(number, cells, [product_id, gtin, name, amount, unit, need_date, note], None)


def _row(number: int, cells: list[Cell], values: list[Cell], default_unit: Unit | None) -> SheetRow | None:
    """One SheetRow from the cells of its fields, or None when none of them has a value."""
    id_cell, gtin_cell, name_cell, amount_cell, unit_cell, date_cell, note_cell = values
    problems: list[Msg] = []
    product_id, gtin = _code(id_cell, problems), _code(gtin_cell, problems)
    if gtin and not _DIGITS.fullmatch(gtin):
        problems.append(P_GTIN)
        gtin = ""
    name = _cut(_text(name_cell), problems)
    if _code_kind(product_id) == "gtin" and not gtin:
        product_id, gtin = "", product_id  # a GTIN in the id column
    if _code_kind(gtin) == "id" and not product_id:
        product_id, gtin = gtin, ""
    if not product_id and not gtin and _code_kind(name):  # a code in the name column
        product_id, gtin = (name, "") if _code_kind(name) == "id" else ("", name)
        name = ""
    amount, amount_unit = _amount(amount_cell, problems)
    unit_text = _text(unit_cell)
    unit = _unit(unit_text, problems) if unit_text else amount_unit or default_unit
    if unit_text and unit and amount_unit and unit != amount_unit:
        problems.append(P_UNIT_CLASH)
        unit = None
    need_date = _date(date_cell, problems)
    note = _cut(_text(note_cell), problems)
    if not (product_id or gtin or name):
        if not (amount is not None or unit or need_date or note or problems):
            return None  # values only in columns nobody reads
        problems.append(P_NO_ITEM)
    return SheetRow(
        row_number=number,
        product_id=product_id,
        gtin=gtin,
        name=name,
        amount=amount,
        unit=unit,
        need_date=need_date,
        note=note,
        raw_text=_raw(cells),
        problems=_unique(problems),
    )


# ---- values ------------------------------------------------------------------------------------------------------


def _text(cell: Cell) -> str:
    """A cell as display text, with runs of whitespace (line breaks, no-break spaces) as one space."""
    if cell is None:
        return ""
    if isinstance(cell, bool):
        return "TRUE" if cell else "FALSE"
    if isinstance(cell, datetime):
        return cell.date().isoformat() if cell.time() == time() else cell.isoformat(sep=" ")
    if isinstance(cell, date | time):
        return cell.isoformat()
    if isinstance(cell, float):
        return str(int(cell)) if cell.is_integer() else repr(cell)
    return " ".join(str(cell).split())


def _cut(text: str, problems: list[Msg]) -> str:
    if len(text) <= MAX_CELL:
        return text
    problems.append(P_CUT)
    return text[:MAX_CELL]


def _raw(cells: list[Cell]) -> str:
    text = " | ".join(t[:MAX_CELL] for t in map(_text, cells) if t)
    return text if len(text) <= MAX_RAW else text[: MAX_RAW - 1] + "…"


def _code(cell: Cell, problems: list[Msg]) -> str:
    """A product id or GTIN cell as text: 464306.0 -> '464306', spaces and hyphens dropped."""
    if isinstance(cell, float) and cell.is_integer():
        cell = int(cell)
    text = re.sub(r"[\s-]", "", _text(cell)).lstrip("'")
    if re.fullmatch(r"[0-9]+\.0+", text):
        text = text.split(".")[0]
    if _SCIENTIFIC.fullmatch(text):
        problems.append(P_CODE_EXP)
        return ""
    return _cut(text, problems)


def _code_kind(text: str) -> Literal["id", "gtin"] | None:
    if not _DIGITS.fullmatch(text):
        return None
    return "id" if len(text) == 6 else "gtin" if len(text) in GTIN_LENGTHS else None


def _amount(cell: Cell, problems: list[Msg]) -> tuple[Decimal | None, Unit | None]:
    """The amount, and a unit written in the same cell ('20 kg')."""
    if not _text(cell):
        return None, None
    if isinstance(cell, bool | date | time):
        problems.append(P_AMOUNT)
        return None, None
    if isinstance(cell, int | float):
        try:
            return _positive(Decimal(str(cell)), problems), None
        except InvalidOperation:
            problems.append(P_AMOUNT)
            return None, None
    match = _AMOUNT.fullmatch(_GROUP_SPACE.sub("", _text(cell)))
    if match is None:
        problems.append(P_AMOUNT)
        return None, None
    sign, number, unit_text = match.groups()
    unit = _unit(unit_text.strip(), problems) if unit_text else None
    if _UNCLEAR.fullmatch(number):
        problems.append(P_AMOUNT_UNCLEAR)
        return None, unit
    value = _number(number)
    if value is None:
        problems.append(P_AMOUNT)
        return None, unit
    return _positive(-value if sign in ("-", "−") else value, problems), unit


def _number(text: str) -> Decimal | None:
    """'1,5' and '1.5' -> 1.5; '1.000,5' and '1,000.5' -> 1000.5; '1.000.000' -> 1000000."""
    if "." in text and "," in text:
        point = max(text.rfind("."), text.rfind(","))
        whole, fraction = text[:point], text[point + 1 :]
        if not (_DIGITS.fullmatch(whole) or _THOUSANDS.fullmatch(whole)) or not _DIGITS.fullmatch(fraction):
            return None
        text = re.sub(r"[.,]", "", whole) + "." + fraction
    elif text.count(".") + text.count(",") > 1:
        if not _THOUSANDS.fullmatch(text):
            return None
        text = re.sub(r"[.,]", "", text)
    try:
        return Decimal(text.replace(",", "."))
    except InvalidOperation:
        return None


def _positive(value: Decimal, problems: list[Msg]) -> Decimal | None:
    if not value.is_finite():
        problems.append(P_AMOUNT)
        return None
    if value <= 0:
        problems.append(P_AMOUNT_ZERO)
        return None
    if value > MAX_AMOUNT:
        problems.append(P_AMOUNT_BIG)
        return None
    return value.quantize(Decimal(1)) if value == value.to_integral_value() else value.normalize()


def _unit(text: str, problems: list[Msg]) -> Unit | None:
    unit = _UNITS.get(text.casefold().strip(" ."))
    if unit is None:
        problems.append(P_UNIT)
    return unit


def _date(cell: Cell, problems: list[Msg]) -> str | None:
    """ISO, d.m.yyyy, d.m.yy, an Excel date or datetime cell, or an Excel serial number; None when empty."""
    if not _text(cell):
        return None
    if isinstance(cell, datetime):
        day: date | None = cell.date()
    elif isinstance(cell, date):
        day = cell
    elif isinstance(cell, bool | time):
        day = None
    elif isinstance(cell, int | float):
        day = _serial(cell)
    else:
        day = _date_text(_text(cell))
    if day is None or not 2000 <= day.year <= 2099:
        problems.append(P_DATE)
        return None
    return day.isoformat()


def _date_text(text: str) -> date | None:
    try:
        if iso := _ISO_DATE.fullmatch(text):
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        if fi := _FI_DATE.fullmatch(text):
            year = int(fi.group(3)) + (2000 if len(fi.group(3)) == 2 else 0)
            return date(year, int(fi.group(2)), int(fi.group(1)))
    except ValueError:  # 31.2.2026
        return None
    if re.fullmatch(r"[0-9]{5}(?:\.[0-9]+)?", text):
        return _serial(float(text))
    return None


def _serial(value: float) -> date | None:
    """An Excel serial day number (1900 date system): 46342 -> 2026-11-16."""
    if not 1 <= value < 2_958_466:
        return None
    try:
        return from_excel(value).date()
    except (OverflowError, ValueError):
        return None


def _unique(problems: list[Msg]) -> list[Msg]:
    seen: dict[tuple[str, str], Msg] = {}
    for p in problems:
        seen.setdefault((p.fi, p.en), p)
    return list(seen.values())


def _error(code: str) -> SheetError:
    status, fi, en = _ERRORS[code]
    return SheetError(status, code, fi, en)


# ---- the template --------------------------------------------------------------------------------------------

TEMPLATE_HEADER = ("tuotenumero", "tuote", "määrä", "yksikkö", "toimituspäivä", "lisätieto")
TEMPLATE_ROWS: tuple[tuple[str, str, int | float, str, date | None, str], ...] = (
    ("464306", "kevytmaitojuoma laktoositon", 1000, "l", date(2026, 11, 16), ""),
    ("", "voi", 20, "kg", date(2026, 11, 16), ""),
    ("", "kananmuna", 180, "kpl", None, ""),
    ("", "vehnäjauho", 12.5, "kg", date(2026, 11, 17), "takaovelle"),
)


@lru_cache(maxsize=1)
def template_xlsx() -> bytes:
    """The order list template as .xlsx; the same columns and rows as web/public/tilauslista-pohja.csv."""
    book = Workbook()
    sheet = book.active
    sheet.title = "Tilauslista"
    sheet.append(TEMPLATE_HEADER)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for values in TEMPLATE_ROWS:
        sheet.append([v if v != "" else None for v in values])
    for row in sheet.iter_rows(min_row=2):
        row[0].number_format = "@"  # ids are codes, not numbers
        row[4].number_format = "d.m.yyyy"
    for column, width in zip("ABCDEF", (14, 32, 10, 10, 16, 24), strict=True):
        sheet.column_dimensions[column].width = width
    sheet.freeze_panes = "A2"
    units = DataValidation(type="list", formula1='"l,kg,kpl"', allow_blank=True)
    sheet.add_data_validation(units)
    units.add(f"D2:D{MAX_ROWS + 1}")
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()
