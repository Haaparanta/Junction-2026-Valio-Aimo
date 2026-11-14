"""One matcher for imported rows (docs/basket-plan.md B-07): a product id, a GTIN or a name to catalogue products.

Sheet imports (M25) and photo imports (M28) use it; voice and dish lines go through stubs.offers() with heads and
exclusions instead. Real search (PLAN M4) replaces the insides of catalogue_entries() and match_item() and keeps
their signatures. Names and cell values are data: they are compared, never followed, and never copied into notes
(only a well-formed six-digit id or a digits-only GTIN is).

How a name is matched:
1. Both sides are normalised: casefolded, Finnish letters kept (ä, ö, å), other accents dropped, punctuation and
   pack sizes (1 l, 0,5 l, 10 g, 4x5 kg, 2,5 dl, 12 kpl ...) removed.
2. A name that is exactly one catalogue name (the same words and pack sizes, in any order) is that product.
3. Otherwise each entry gets a score from 0 to 100: WORD_WEIGHT of it for how well the name holds each query word,
   plus HEAD_WORD_BONUS when the query's last word (the head of a Finnish noun phrase) is a whole word of the name,
   or HEAD_END_BONUS when a name word ends with it (a compound with that head). So 'voi' prefers butter over
   'maapähkinävoi', and 'lohi' prefers salmon over 'kirjolohi'. In catalogue-style names the head is the last word
   before a comma ('voi, suolaton'), and a trailing 'laktoositon' or 'suolaton' is never the head.
4. ONE, GAP and CLOSE turn the scores into one, several or none. A wrong product priced silently is the worst
   outcome, so 'one' also needs every query word in the name: a 'luomu' or 'laktoositon' it lacks asks the buyer.
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from rapidfuzz import fuzz

MatchKind = Literal["exact", "one", "several", "none"]
MatchVia = Literal["product_id", "gtin", "name", "none"]


@dataclass(frozen=True)
class CatalogueEntry:
    product_id: str
    name: str
    gtin: str | None = None


@dataclass(frozen=True)
class Candidate:
    product_id: str
    name: str
    score: float  # 0-100; 100 for an exact id, GTIN or name


@dataclass(frozen=True)
class MatchResult:
    """What one row or list item matched.

    kind and candidates: exact and one have the product as their only candidate (from the id or GTIN, or a clear name
    match); several has 1 to MAX_CANDIDATES for the buyer to choose from, best first (a single weak candidate is a
    "did you mean"); none has no candidates.
    via: the key that decided; 'none' when there was nothing usable to match on.
    note: a short English explanation for logs and warnings; of the row's text it repeats only a well-formed id or
    GTIN, never a name.
    """

    kind: MatchKind
    via: MatchVia
    candidates: tuple[Candidate, ...]
    note: str


# Word scores are coarse on purpose: a query word is in the name whole (100), as the same word with an ending, a
# typo or without umlauts (SAME), inside a compound (PART_CREDIT), close by rapidfuzz ratio (FUZZY_FOUND and up), or
# not at all (0). Nothing in between, because rapidfuzz gives 'servetit' and 'kevytmaito' 56 by chance.
WORD_WEIGHT = 0.6  # share of the score for the query words found; the head bonuses add up to the other 40
HEAD_WORD_BONUS = 40  # the head is a whole name word: 'voi' in 'Valio Eila voi 4x5 kg'
HEAD_END_BONUS = 20  # a name word ends with the head: 'voi' in 'maapähkinävoi', 'kerma' in 'vispikerma'
SAME = 95  # the same word: 'kananmunat', 'maitoa', 'maapahkinavoi', 'kanamuna'
PART_CREDIT = 80  # a query word inside a compound name word: 'maito' in 'kevytmaitojuoma'
SAME_WORD_RATIO = 90  # rapidfuzz ratio from which two words of 5+ letters are the same word (one typo)
FUZZY_FOUND = 85  # the lowest ratio that still finds a word; 'kevytmaitojuoma' and 'maitojuoma' are 80
PART_MIN = 4  # shortest word looked for inside a compound: 'voi' inside 'voisilmäpulla' is a bun, not butter
END_MIN = 3  # shortest head looked for at the end of a compound, so 'voi' still finds 'maapähkinävoi'

# Thresholds, chosen from the scores above and checked on the stub catalogue and the names in tests/test_match.py:
# * ONE = 85: a name with every query word and the head as a whole word scores at least 88; with the head only at
#   the end of a compound it scores at most 80. So 'one' needs the head as a whole word: 'kerma' alone always asks.
# * GAP = 15: two names that both hold every query word and the head are at most 12 apart, so they never give
#   'one'; a rival that lacks one word of a two-, three- or four-word query is 30, 20 or 15 behind.
# * CLOSE = 35: one word found as a compound end (68) or inside a compound (48) is a candidate; a two-word query
#   whose head is missing (30) is not, so 'laktoositon jäätelö' does not offer every lactose-free milk.
ONE = 85
GAP = 15
CLOSE = 35
MAX_CANDIDATES = 5

GTIN_LENGTHS = (8, 12, 13, 14)
_ID = re.compile(r"\d{6}")
_PACK_UNIT = {"litra": "l", "litraa": "l", "ltr": "l", "kilo": "kg", "kiloa": "kg", "gr": "g"}
_PACK_UNIT |= dict.fromkeys(["pcs", "pc", "st", "stk", "ea"], "kpl")
_PACK_UNITS = "|".join(sorted(["kg", "g", "mg", "l", "dl", "cl", "ml", "kpl", *_PACK_UNIT], key=len, reverse=True))
_PACK = re.compile(rf"(?<!\w)\d+(?:[.,]\d+)?(?:\s*[x×*]\s*\d+(?:[.,]\d+)?)?\s*(?:{_PACK_UNITS})(?!\w)")
_WORD = re.compile(r"\d+(?:[.,]\d+)*|[^\W\d_]+")
_FINNISH = frozenset("äöå")
_PLAIN = str.maketrans("äöå", "aoa")
_ENDINGS = ("ta", "tä", "t", "a", "ä", "n")  # partitive, plural and genitive endings on a base form
_PRIVATIVE = ("ton", "tön")  # laktoositon, gluteeniton, suolaton: describe the head, never are it
_LIST_COMMA = re.compile(r"(?<!\d),|,(?!\d)")  # 'voi, suolaton', but not the decimal comma in '1,5 %'


def catalogue_entries() -> tuple[CatalogueEntry, ...]:
    """The stub catalogue as match entries. stubs is imported here so that it may import this module one day."""
    from . import stubs

    return tuple(
        CatalogueEntry(product_id=p.id, name=p.name, gtin=_digits(getattr(p, "gtin", None)) or None)
        for p in stubs.PRODUCTS.values()
    )


def match_item(
    product_id: str = "", gtin: str = "", name: str = "", entries: Iterable[CatalogueEntry] | None = None
) -> MatchResult:
    """Match one row or list item: the product id first, then the GTIN, then the name.

    An unknown or malformed id or GTIN falls back to the next key, and the note says so. When the id and the GTIN,
    or the id and the name, clearly point to different products, the answer is 'several' with both: one is a typo.
    """
    entries = _unique(catalogue_entries() if entries is None else entries)
    notes: list[str] = []
    hit: CatalogueEntry | None = None
    via: MatchVia = "none"

    pid = product_id.strip()
    if pid and not _ID.fullmatch(pid):
        notes.append("the product id is not a six-digit number")
    elif pid:
        hit = next((e for e in entries if e.product_id == pid), None)
        if hit is None:
            notes.append(f"product id {pid} is not in the catalogue")
        else:
            via = "product_id"

    code = _digits(gtin)
    if gtin.strip() and len(code) not in GTIN_LENGTHS:
        notes.append("the GTIN is not 8, 12, 13 or 14 digits")
    elif gtin.strip():
        same = [e for e in entries if e.gtin and _digits(e.gtin).lstrip("0") == code.lstrip("0")]
        if not same:
            notes.append(f"GTIN {code} is not in the catalogue")
        elif hit is None and len(same) > 1:
            return _result("several", "gtin", [(e, 100.0) for e in same], [*notes, "the GTIN is on several products"])
        elif hit is None:
            hit, via = same[0], "gtin"
        elif all(e.product_id != hit.product_id for e in same):
            both = [(hit, 100.0), (same[0], 100.0)]
            return _result("several", via, both, [*notes, "the product id and the GTIN are different products"])

    if hit is not None:
        other = _name_points_elsewhere(name, hit, entries)
        if other is not None:
            key = "product id" if via == "product_id" else "GTIN"
            return _result("several", via, [(hit, 100.0), other], [*notes, f"the {key} and the name differ"])
        return _result("exact", via, [(hit, 100.0)], notes)
    if not name.strip():
        return _result("none", "none", [], notes or ["no product id, GTIN or name to match"])
    by_name = _match_name(name, entries)
    return MatchResult(by_name.kind, by_name.via, by_name.candidates, _join([*notes, by_name.note]))


def _match_name(name: str, entries: tuple[CatalogueEntry, ...]) -> MatchResult:
    words, packs = _normalise(name)
    head = _head(name)
    if not head:
        return _result("none", "none", [], ["the name has no words to match"])
    same_name = [e for e in entries if _same_name(e.name, words, packs)]
    if len(same_name) == 1:
        return _result("one", "name", [(same_name[0], 100.0)], [])
    scored = [(e, *_score(words, head, e.name)) for e in entries]
    scored.sort(key=lambda t: (-t[1], -_closeness(words, t[0].name)))  # stable: ties keep the catalogue order
    close = [(e, s, complete) for e, s, complete in scored if s >= CLOSE]
    if not close:
        return _result("none", "name", [], ["no catalogue name is close"])
    best, top, top_complete = close[0]
    gap = top - close[1][1] if len(close) > 1 else 100.0
    if top >= ONE and top_complete and gap >= GAP:
        return _result("one", "name", [(best, top)], [])
    note = "several names are close" if len(close) > 1 else "one name is close but not certain"
    return _result("several", "name", [(e, s) for e, s, _ in close], [note])


def _name_points_elsewhere(
    name: str, hit: CatalogueEntry, entries: tuple[CatalogueEntry, ...]
) -> tuple[CatalogueEntry, float] | None:
    """The product the name clearly names instead of the id's or GTIN's, when the hit lacks the name's words."""
    if not name.strip():
        return None
    by_name = _match_name(name, entries)
    if by_name.kind != "one" or by_name.candidates[0].product_id == hit.product_id:
        return None
    if _score(_normalise(name)[0], _head(name), hit.name)[1]:
        return None
    best = by_name.candidates[0]
    return next(e for e in entries if e.product_id == best.product_id), best.score


def _result(
    kind: MatchKind, via: MatchVia, scored: list[tuple[CatalogueEntry, float]], notes: list[str]
) -> MatchResult:
    candidates = tuple(Candidate(e.product_id, e.name, round(s, 1)) for e, s in scored[:MAX_CANDIDATES])
    return MatchResult(kind, via, candidates, _join(notes))


def _join(notes: list[str]) -> str:
    return "; ".join(n for n in notes if n)


def _score(words: tuple[str, ...], head: str, name: str) -> tuple[float, bool]:
    """The entry's score, and whether it is complete: it holds every query word, and the head as a whole word."""
    name_words = _normalise(name)[0]
    if not name_words or not words or not head:
        return 0.0, False
    found = [max(_word_score(w, n) for n in name_words) for w in words]
    head_whole = any(_word_score(head, n) >= SAME for n in name_words)
    head_end = any(_ends_with(n, head) for n in name_words)
    bonus = HEAD_WORD_BONUS if head_whole else HEAD_END_BONUS if head_end else 0
    return WORD_WEIGHT * sum(found) / len(found) + bonus, head_whole and all(f > 0 for f in found)


def _word_score(word: str, name_word: str) -> float:
    if word == name_word:
        return 100.0
    if word in _forms(name_word) or name_word in _forms(word) or word.translate(_PLAIN) == name_word.translate(_PLAIN):
        return SAME
    ratio = fuzz.ratio(word, name_word) if min(len(word), len(name_word)) >= 5 else 0.0
    if ratio >= SAME_WORD_RATIO:
        return SAME
    inside = any(len(f) >= PART_MIN and f in name_word for f in _forms(word)) or _ends_with(name_word, word)
    return max(PART_CREDIT if inside else 0.0, ratio if ratio >= FUZZY_FOUND else 0.0)


def _ends_with(name_word: str, head: str) -> bool:
    """name_word is a compound whose last part is head, allowing an ending on either: 'vispikerma' and 'kerma'."""
    return any(
        len(n) > len(h) and n.endswith(h)
        for n in _forms(name_word)
        for h in _forms(head)
        if len(h) >= END_MIN and _has_letter(h)
    )


def _closeness(words: tuple[str, ...], name: str) -> float:
    """Orders candidates with the same score: the name with fewer other words first."""
    return fuzz.token_sort_ratio(" ".join(words), " ".join(_normalise(name)[0]))


def _head(name: str) -> str:
    """The head word: the last word, or the last before a list comma, skipping trailing privative adjectives."""
    before_comma = _LIST_COMMA.split(name, maxsplit=1)[0]
    words = [w for w in _normalise(before_comma)[0] if _has_letter(w)]
    words = words or [w for w in _normalise(name)[0] if _has_letter(w)]
    while len(words) > 1 and words[-1].endswith(_PRIVATIVE):
        words.pop()
    return words[-1] if words else ""


def _same_name(name: str, words: tuple[str, ...], packs: tuple[str, ...]) -> bool:
    """The query is this catalogue name: the same words, in any order, and the same pack sizes."""
    other_words, other_packs = _normalise(name)
    return other_packs == packs and sorted(other_words) == sorted(words)


@lru_cache(maxsize=8192)
def _forms(word: str) -> frozenset[str]:
    """The word and the base forms it may be inflected from: 'kananmunat' -> {'kananmunat', 'kananmuna'}."""
    if not _has_letter(word):
        return frozenset({word})
    return frozenset({word, *(word[: -len(e)] for e in _ENDINGS if word.endswith(e) and len(word) - len(e) >= 3)})


@lru_cache(maxsize=8192)
def _normalise(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(words, pack sizes) of a name: 'Valio Eila voi 4x5 kg' -> (('valio', 'eila', 'voi'), ('4x5kg',))."""
    text = unicodedata.normalize("NFKC", text).casefold()
    text = "".join(c if c in _FINNISH else _strip_accents(c) for c in text)
    packs = tuple(sorted(_pack(m.group(0)) for m in _PACK.finditer(text)))
    words = tuple(w.replace(",", ".") for w in _WORD.findall(_PACK.sub(" ", text)) if len(w) > 1 or w.isdigit())
    return words, packs


def _pack(text: str) -> str:
    """One spelling per pack size: '4 x 5 kg' -> '4x5kg', '1,0 ltr' -> '1l'."""
    compact = re.sub(r"\s+", "", text).replace("×", "x").replace("*", "x")
    number, unit = re.fullmatch(r"([\d.,x]+?)([^\d.,x]+)", compact).groups()
    parts = [f"{float(p.replace(',', '.')):g}" for p in number.split("x")]
    return "x".join(parts) + _PACK_UNIT.get(unit, unit)


def _strip_accents(c: str) -> str:
    return "".join(d for d in unicodedata.normalize("NFD", c) if not unicodedata.combining(d))


def _has_letter(word: str) -> bool:
    return any(c.isalpha() for c in word)


def _digits(value: object) -> str:
    """The digits of a GTIN with spaces and hyphens removed, or '' when anything else is in it."""
    text = re.sub(r"[\s-]", "", "" if value is None else str(value))
    return text if text.isdigit() else ""


def _unique(entries: Iterable[CatalogueEntry]) -> tuple[CatalogueEntry, ...]:
    by_id: dict[str, CatalogueEntry] = {}
    for e in entries:
        by_id.setdefault(e.product_id, e)
    return tuple(by_id.values())
