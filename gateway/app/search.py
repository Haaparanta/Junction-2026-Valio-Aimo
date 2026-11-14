"""Product search over catalog.db (PLAN M4, findings S-01..S-07).

The LLM plans and the gateway executes: the caller sends Finnish base-form product-type heads, exclusions, claims,
allergens and a temperature class, and this module applies every one of them in code.

How one search runs:
1. **Candidates.** Each head is matched on the end of a word of the fi name through the reversed-token FTS5 column
   (`rev_fi:"otiam"*` is every word ending in "maito"), so "kevytmaitojuoma" is milk and "maitosuklaa" is not. With no
   heads, heads come from the query (a small fi/sv/en synonym table, else the last content word, since a Finnish noun
   phrase ends in its head); if those find nothing, the query words are prefix-matched in every name and the brand.
2. **Head checks in code.** The word that ends in the head must not be a hyphenated modifier ("Voi-kristallipulla" is
   a bun), and the part before the head must not be a known modifier that makes another product (S-03, S-04:
   kirjolohi is rainbow trout, maapähkinävoi is peanut butter). A caller who wants one of those names it as the head.
3. **Hard filters** (S-05, three-valued: a constraint passes only on an explicit code; unknown never passes):
   exclusion words, claims (LOW_LACTOSE never satisfies FREE_FROM_LACTOSE), allergens from `expand_diet` (gluten-free
   adds wheat, barley, rye and oats; oats only when the buyer does not allow them), temperature (an unknown class is
   kept and warned about, D-08), organic (label or "luomu" in the name), and the placeholder junk filter.
4. **Ranking.** Extra query words found in the names first ('naudan', 'kuorittu'), then the categories most survivors
   share (S-01 category votes), then plain products over variants (portion packs, breaded, cubed, cooked or flavoured
   versions, a head inside 'X ja Y'), then head words several survivors share over one-offs ('maitorahka' before
   'luumurahka'), then full GS1 records over ERP-only ones, then shorter names.
5. **Robust input** (M4.4). Every MATCH term is built from word tokens and double-quoted, so FTS syntax in the input
   ("AND", "*", quotes, parentheses) is only text. If an FTS query still fails, or nothing matches, the trigram table
   and rapidfuzz give close spellings, marked as fuzzy.

`search(conn, query, ...)` returns a SearchResult with the hits (compact records, why and warnings), the number of
matches, and an interpretation (heads used, filters, dropped counts, category votes) the caller can show or log.
"""

import json
import re
import sqlite3
import time
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal

from rapidfuzz import fuzz

from .catalog import allergen_status, has_claim, summary_fields
from .catalog.text import tokens
from .diet import expand_diet

Temperature = Literal["any", "chilled", "frozen", "ambient"]
Mode = Literal["heads", "text", "fuzzy"]

DEFAULT_LIMIT = 10
MAX_LIMIT = 50
MAX_QUERY_CHARS = 200
MAX_TERMS = 12  # heads, exclusions and query words each; more is not a real need, only a slower query
FUZZY_MIN_SCORE = 75  # rapidfuzz partial_ratio from which a name is a close spelling of the query
FUZZY_POOL = 300

# Compound modifiers that turn a head into another product (S-03, S-04). They apply to a head that starts with the
# key ("maitojuoma" uses the "maito" list) and only when the modifier is in the same word, or joined by a hyphen.
DEFAULT_MODIFIERS: dict[str, tuple[str, ...]] = {
    "maito": ("kahvi", "suklaa", "kaakao", "kookos", "manteli", "kaura", "soija", "riisi", "latte"),
    "voi": ("maapähkinä", "pähkinä", "kaakao", "manteli", "cashew", "shea", "kookos"),
    "lohi": ("kirjo",),
    "muna": ("suklaa",),
    "murska": ("tomaatti",),
    "kerma": ("kookos", "kaura", "soija"),
    # juustoleipä is a cheese, pikkuleipä a biscuit, näkkileipä crispbread, voileipä and eväsleipä sandwiches
    "leipä": ("juusto", "pikku", "näkki", "voi", "eväs"),
    "peruna": ("ranskan", "makea"),  # ranskanperuna is French fries, makeaperuna sweet potato
}
# Modifiers that keep the product but make it a variant (portion packs, coffee and flavoured versions): kept, ranked
# after the plain product.
VARIANT_MODIFIERS: tuple[str, ...] = (
    "annos",
    "mauste",
    "grilli",
    "yrtti",
    "valkosipuli",
    "kahvi",
    "hapan",
    "lohko",
    "pannu",
)
# Processing words anywhere in the fi name (word starts): breaded, cubed, cooked and seasoned versions of a product.
# Ranked after the plain product unless the query asks for them (query words rank first).
VARIANT_WORDS: tuple[str, ...] = (
    "leivite",
    "paneroi",
    "tempura",
    "nuget",
    "kuutio",
    "suikale",
    "viipale",
    "marinoi",
    "maustettu",
    "grillat",
    "kypsä",
    "keitetty",
    # flavoured versions
    "suklaa",
    "kaakao",
    "vanilja",
    "karamelli",
    "caramel",
    "vanilla",
    "chocolate",
    "choco",
    "mansikka",
    "maku",
    "piparkakku",
    "pumpkin",
    "vadelma",
    "mustikka",
    "persikka",
    "mango",
    "luumu",
    "kuningatar",
    "puolukka",
    "sitruuna",
    "lakka",
    "appelsiini",
    "banaani",
    "kirsikka",
    "pannacotta",
    "hassel",
)
_COORDINATORS = frozenset({"ja", "tai", "and", "och", "&", "/", "+"})

# Diet and organic words in the query become filters: the buyer said them, and ignoring one would be unsafe.
_CLAIM_PREFIXES: tuple[tuple[str, str], ...] = (
    ("laktoosit", "FREE_FROM_LACTOSE"),
    ("laktosfri", "FREE_FROM_LACTOSE"),
    ("gluteenit", "FREE_FROM_GLUTEN"),
    ("glutenfri", "FREE_FROM_GLUTEN"),
    ("vegaan", "VEGAN"),
    ("vegan", "VEGAN"),
    ("kasvipohjai", "VEGAN"),
    ("vegetaar", "VEGETARIAN"),
    ("vegetarian", "VEGETARIAN"),
    ("munaton", "FREE_FROM_EGGS"),
    ("munatt", "FREE_FROM_EGGS"),
    ("soijaton", "FREE_FROM_SOY"),
    ("soijatt", "FREE_FROM_SOY"),
)
_CLAIM_PHRASES: dict[tuple[str, str], str] = {
    ("lactose", "free"): "FREE_FROM_LACTOSE",
    ("gluten", "free"): "FREE_FROM_GLUTEN",
    ("plant", "based"): "VEGAN",
    ("egg", "free"): "FREE_FROM_EGGS",
    ("soy", "free"): "FREE_FROM_SOY",
}
# Allergen words in the query: 'maidoton' (milk-free) bans milk itself, which no claim does (lactose-free does not).
_ALLERGEN_PREFIXES: tuple[tuple[str, str], ...] = (("maidot", "AM"), ("mjölkfri", "AM"), ("pähkinät", "AN"))
_ALLERGEN_PHRASES: dict[tuple[str, str], str] = {
    ("milk", "free"): "AM",
    ("dairy", "free"): "AM",
    ("nut", "free"): "AN",
    ("peanut", "free"): "AP",
}
_ORGANIC_WORDS = ("luomu", "organic", "ekologisk", "ekologiska", "eko")
ORGANIC_LABELS = frozenset(
    {"EU_ORGANIC_FARMING", "KRAV_MARK", "OFFICIAL_ECO_LABEL_SUN", "SOIL_ASSOCIATION_ORGANIC_SYMBOL"}
)
CLAIM_ALIASES: dict[str, str] = {
    "LACTOSE_FREE": "FREE_FROM_LACTOSE",
    "GLUTEN_FREE": "FREE_FROM_GLUTEN",
    "EGG_FREE": "FREE_FROM_EGGS",
    "SOY_FREE": "FREE_FROM_SOY",
    "WHEAT_FREE": "FREE_FROM_WHEAT",
}
ALLERGEN_ALIASES: dict[str, str] = {
    "MILK": "AM",
    "MAITO": "AM",
    "GLUTEN": "AW",
    "WHEAT": "UW",
    "EGG": "AE",
    "EGGS": "AE",
    "SOY": "AY",
    "SOYA": "AY",
    "PEANUT": "AP",
    "PEANUTS": "AP",
    "NUTS": "AN",
    "SESAME": "AS",
    "FISH": "AF",
    "OATS": "GO",
    "BARLEY": "GB",
    "RYE": "NR",
    "CELERY": "BC",
    "MUSTARD": "BM",
    "LUPIN": "NL",
    "SULPHITES": "AU",
    "CRUSTACEANS": "AC",
    "MOLLUSCS": "UM",
}
_CODE = re.compile(r"[A-Z0-9_]{1,40}")

# Heads for a query that brings none (findings S-03; fi, sv and en words). Phrases are checked before single words.
SYNONYM_PHRASES: dict[tuple[str, str], tuple[str, ...]] = {
    ("ice", "cream"): ("jäätelö",),
    ("sour", "cream"): ("kermaviili", "hapankerma"),
    ("whipping", "cream"): ("kuohukerma", "vispikerma"),
    ("cooking", "cream"): ("ruokakerma",),
    ("oat", "drink"): ("kaurajuoma",),
    ("oat", "milk"): ("kaurajuoma",),
    ("milk", "drink"): ("maitojuoma",),
    ("chicken", "breast"): ("rintafilee",),
    ("crushed", "tomatoes"): ("tomaattimurska",),
    ("minced", "meat"): ("jauheliha",),
    ("peanut", "butter"): ("maapähkinävoi",),
}
SYNONYMS: dict[str, tuple[str, ...]] = {
    "maito": ("maito", "maitojuoma"),
    "milk": ("maito", "maitojuoma"),
    "mjölk": ("maito", "maitojuoma"),
    "cream": ("kerma",),
    "grädde": ("kerma",),
    "butter": ("voi",),
    "smör": ("voi",),
    "egg": ("muna",),
    "eggs": ("muna",),
    "ägg": ("muna",),
    "kananmuna": ("muna",),
    "kananmunat": ("muna",),
    "salmon": ("lohi", "lohifilee"),
    "lax": ("lohi", "lohifilee"),
    "lohi": ("lohi", "lohifilee"),
    "potato": ("peruna",),
    "potatoes": ("peruna",),
    "potatis": ("peruna",),
    "cheese": ("juusto",),
    "ost": ("juusto",),
    "flour": ("jauho", "jauhot"),
    "sugar": ("sokeri",),
    "socker": ("sokeri",),
    "rice": ("riisi",),
    "ris": ("riisi",),
    "coffee": ("kahvi",),
    "kaffe": ("kahvi",),
    "bread": ("leipä",),
    "bröd": ("leipä",),
    "quark": ("rahka",),
    "yoghurt": ("jogurtti",),
    "yogurt": ("jogurtti",),
    "juice": ("mehu",),
    "oil": ("öljy",),
    "mince": ("jauheliha",),
    "strawberry": ("mansikka",),
    "strawberries": ("mansikka",),
    "tomato": ("tomaatti",),
    "tomatoes": ("tomaatti",),
}
_STOPWORDS = frozenset(
    "ja tai sekä myös the a an and or of with for in to without ilman och med till för av en ett".split()
)
_UNIT_WORDS = frozenset("kg g l dl cl ml kpl st pcs x".split())
_FOLD = str.maketrans("äöåáàâéèêëíïóôúüñç", "aoaaaaeeeeiioouunc")
_WORD_SPAN = re.compile(r"[^\W_]+")


@lru_cache(maxsize=65536)
def fold(s: str) -> str:
    """Casefold and drop diacritics the way the FTS index does (ä -> a), for comparisons in code."""
    s = unicodedata.normalize("NFC", s).casefold().translate(_FOLD)
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))


def quote(term: str) -> str:
    """An FTS5 string literal: the term in double quotes, inner quotes doubled. Nothing in it is syntax."""
    return '"' + term.replace('"', '""') + '"'


def _clean_text(s: Any, limit: int = MAX_QUERY_CHARS) -> str:
    if not isinstance(s, str):
        return ""
    s = "".join(c if c.isprintable() else " " for c in s)
    return s[:limit].strip()


def _terms(values: Iterable[Any] | None) -> list[str]:
    out: list[str] = []
    for v in values or ():
        t = _clean_text(v, 80)
        if t and t not in out:
            out.append(t)
    return out[:MAX_TERMS]


# ---- request normalisation ---------------------------------------------------------------------


@dataclass(frozen=True)
class Head:
    word: str  # the last word, which a fi name word must end with: 'maito'
    before: tuple[str, ...] = ()  # earlier words of a multi-word head, each the start of some name word
    text: str = ""

    @property
    def folded(self) -> str:
        return fold(self.word)


def parse_heads(values: Iterable[str]) -> list[Head]:
    heads: list[Head] = []
    for v in values:
        toks = [t for t in tokens(v) if t.isalnum()]
        if not toks:
            continue
        h = Head(word=toks[-1], before=tuple(toks[:-1]), text=" ".join(toks))
        if h not in heads:
            heads.append(h)
    return heads[:MAX_TERMS]


def normalise_claims(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    for v in values:
        code = re.sub(r"[\s-]+", "_", v.strip().upper())
        code = CLAIM_ALIASES.get(code, code)
        if _CODE.fullmatch(code) and code not in out:
            out.append(code)
    return out


def normalise_allergens(values: Iterable[str]) -> tuple[list[str], list[str]]:
    """(GS1 codes, values that are not a code): names such as 'milk' map to their code."""
    codes: list[str] = []
    bad: list[str] = []
    for v in values:
        code = v.strip().upper()
        code = ALLERGEN_ALIASES.get(code, code)
        if re.fullmatch(r"[A-Z0-9]{2,3}", code):
            if code not in codes:
                codes.append(code)
        elif code:
            bad.append(v[:40])
    return codes, bad


@dataclass
class QueryWords:
    claims: list[str] = field(default_factory=list)  # diet words found: 'laktoositon' -> FREE_FROM_LACTOSE
    allergens: list[str] = field(default_factory=list)  # allergen words found: 'maidoton' -> AM
    organic: bool = False
    content: list[str] = field(default_factory=list)  # the other words, in order: product words and modifiers


def read_query(query: str) -> QueryWords:
    toks = [t for t in tokens(query) if t]
    out = QueryWords()
    skip: set[int] = set()
    for i, (a, b) in enumerate(zip(toks, toks[1:], strict=False)):
        claim = _CLAIM_PHRASES.get((a, b))
        allergen = _ALLERGEN_PHRASES.get((a, b))
        if claim:
            out.claims.append(claim)
            skip.update((i, i + 1))
        elif allergen:
            out.allergens.append(allergen)
            skip.update((i, i + 1))
    for i, t in enumerate(toks):
        if i in skip:
            continue
        claim = next((c for p, c in _CLAIM_PREFIXES if t.startswith(p)), None)
        allergen = next((c for p, c in _ALLERGEN_PREFIXES if t.startswith(p)), None)
        if claim:
            out.claims.append(claim)
        elif allergen:
            out.allergens.append(allergen)
        elif t in _ORGANIC_WORDS:
            out.organic = True
        elif t in _STOPWORDS or t in _UNIT_WORDS or not t.isalpha() or len(t) < 2:
            continue
        else:
            out.content.append(t)
    out.claims = list(dict.fromkeys(out.claims))
    out.allergens = list(dict.fromkeys(out.allergens))
    out.content = out.content[:MAX_TERMS]
    return out


def heads_from_query(words: Sequence[str]) -> tuple[list[str], set[str]]:
    """Heads for a query without any, and the query words they used up."""
    heads: list[str] = []
    used: set[str] = set()
    for a, b in zip(words, words[1:], strict=False):
        if (a, b) in SYNONYM_PHRASES:
            heads.extend(SYNONYM_PHRASES[(a, b)])
            used.update((a, b))
    for w in words:
        if w not in used and w in SYNONYMS:
            heads.extend(SYNONYMS[w])
            used.add(w)
    if not heads and words:
        heads.append(words[-1])
        used.add(words[-1])
    return list(dict.fromkeys(heads)), used


# ---- result ------------------------------------------------------------------------------------


@dataclass
class Hit:
    product_id: str
    record: dict[str, Any]
    why: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fuzzy_score: float | None = None

    def summary(self) -> dict[str, Any]:
        """The contract's ProductSummary fields."""
        return summary_fields(self.record)

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.summary(),
            "why": self.why,
            "warnings": self.warnings,
            **({"fuzzy_score": self.fuzzy_score} if self.fuzzy_score is not None else {}),
        }


@dataclass
class SearchResult:
    hits: list[Hit]
    total_matches: int
    mode: Mode
    interpretation: dict[str, Any]
    warnings: list[str] = field(default_factory=list)

    @property
    def ids(self) -> list[str]:
        return [h.product_id for h in self.hits]

    def as_dict(self) -> dict[str, Any]:
        return {
            "products": [h.as_dict() for h in self.hits],
            "total_matches": self.total_matches,
            "mode": self.mode,
            "interpretation": self.interpretation,
            "warnings": self.warnings,
        }


# ---- candidates --------------------------------------------------------------------------------

_SELECT = "SELECT p.num, p.id, p.category, p.record FROM products p"


def head_match_expr(heads: Sequence[Head]) -> str:
    """rev_fi : ("otiam"* OR "amoujotiam"*): every fi word that ends in one of the heads."""
    terms = [quote(h.word[::-1]) + "*" for h in heads]
    return "rev_fi : (" + " OR ".join(terms) + ")"


def text_match_expr(words: Sequence[str], op: str = "AND") -> str:
    """Each query word as a prefix (whole word under three letters) in any name or the brand."""
    terms = [quote(w) + ("*" if len(w) >= 3 else "") for w in words]
    return "{name_fi name_sv name_en brand} : (" + f" {op} ".join(terms) + ")"


def _fts_rows(conn: sqlite3.Connection, expr: str) -> list[sqlite3.Row]:
    sql = _SELECT + " JOIN product_fts f ON f.rowid = p.num WHERE product_fts MATCH ?"
    return conn.execute(sql, (expr,)).fetchall()


def _fuzzy_rows(conn: sqlite3.Connection, text: str) -> list[tuple[Any, float]]:
    """Close spellings: trigram candidates scored by rapidfuzz. A query without a word of three letters has none."""
    q = fold(text)
    grams = sorted({w for w in re.findall(r"\w+", q) if len(w) >= 3}, key=len, reverse=True)[:MAX_TERMS]
    rows: list[Any] = []
    if grams:
        # Every three-letter window of the words, so one typo still leaves most windows matching.
        windows = sorted({w[i : i + 3] for w in grams for i in range(len(w) - 2)})[:60]
        expr = " OR ".join(quote(g) for g in windows)
        try:
            rows = conn.execute(
                _SELECT + " JOIN product_trigram t ON t.rowid = p.num WHERE product_trigram MATCH ?", (expr,)
            ).fetchall()
        except sqlite3.Error:
            rows = []
    scored = []
    for r in rows:
        names = json.loads(r[3])
        best = max(fuzz.partial_ratio(q, fold(names.get(k) or "")) for k in ("name_fi", "name_sv", "name_en", "brand"))
        if best >= FUZZY_MIN_SCORE:
            scored.append((r, float(best)))
    scored.sort(key=lambda x: (-x[1], x[0][1]))
    return scored[:FUZZY_POOL]


# ---- head checks -------------------------------------------------------------------------------


def _name_words(name: str) -> list[tuple[str, int, int]]:
    s = unicodedata.normalize("NFC", name).casefold()
    return [(m.group(), m.start(), m.end()) for m in _WORD_SPAN.finditer(s)]


def _joined_after(s: str, end: int) -> bool:
    """The word ending at `end` is the first part of a hyphen or slash compound, so it is not the head."""
    if end >= len(s) - 1:
        return False
    if s[end] == "-":
        return True  # 'voi-kristallipulla', and the coordinated 'lohi- ja katkarapu...'
    return s[end] == "/" and s[end + 1].isalpha()


def _blocked_for(head: Head) -> tuple[str, ...]:
    out: list[str] = []
    for key, mods in DEFAULT_MODIFIERS.items():
        if head.word.startswith(key):
            out.extend(m for m in mods if m not in head.word)
    return tuple(out)


@dataclass(frozen=True)
class HeadMatch:
    head: Head
    word: str  # the fi name word that ends with the head
    modifier: str  # the part of the word before the head, folded ('kevyt' in 'kevytmaitojuoma')
    coordinated: bool  # next to 'ja', '&' or '/': 'kermaviili ja sipuli' is a flavour, not the product


def _coordinated(s: str, words: Sequence[tuple[str, int, int]], i: int) -> bool:
    """The word is joined to a neighbour by a coordinator ('ja', 'tai', '&', '/')."""
    if i + 1 < len(words):
        gap = s[words[i][2] : words[i + 1][1]].strip()
        if gap in _COORDINATORS or (not gap and words[i + 1][0] in _COORDINATORS):
            return True
        if words[i + 1][0] in _COORDINATORS and i + 2 < len(words):
            return True
    if i > 0:
        gap = s[words[i - 1][2] : words[i][1]].strip()
        if gap in _COORDINATORS or words[i - 1][0] in _COORDINATORS:
            return True
    return False


def match_head(name_fi: str, heads: Sequence[Head]) -> HeadMatch | str | None:
    """The first head a fi name word ends with.

    Returns a reason string instead when a word ends with a head but is ruled out ('hyphen_modifier',
    'compound_modifier'), and None when no word ends with any head.
    """
    s = unicodedata.normalize("NFC", name_fi).casefold()
    words = _name_words(name_fi)
    folded = [fold(w) for w, _, _ in words]
    reason: str | None = None
    for i, (w, _, end) in enumerate(words):
        fw = folded[i]
        for h in heads:
            if not fw.endswith(h.folded):
                continue
            if _joined_after(s, end):
                # 'Voi-kristallipulla' (the bun is the head), 'Lohi- ja katkarapuhampurilainen', 'Lohi/Seitikuutiot'
                reason = reason or "hyphen_modifier"
                continue
            modifier = fw[: len(fw) - len(h.folded)]
            start = words[i][1]
            if not modifier and i > 0 and start > 0 and s[start - 1] == "-":
                modifier = folded[i - 1]  # 'maapähkinä-voi'
            blocked = _blocked_for(h)
            if modifier and any(modifier.endswith(fold(m)) for m in blocked):
                reason = reason or "compound_modifier"
                continue
            if h.before and not all(any(f.startswith(fold(b)) for f in folded) for b in h.before):
                continue
            return HeadMatch(h, w, modifier, _coordinated(s, words, i))
    return reason


# ---- filters -----------------------------------------------------------------------------------


def _excluded(record: Mapping[str, Any], terms: Sequence[str]) -> str | None:
    """The first exclusion term in a name: a substring of any name word, or a whole word under four letters."""
    for lang in ("name_fi", "name_sv", "name_en"):
        words = [fold(w) for w in tokens(record.get(lang) or "")]
        joined = " " + " ".join(words) + " "
        for t in terms:
            ft = " ".join(fold(w) for w in tokens(t))
            if not ft:
                continue
            if len(ft) < 4:
                if f" {ft} " in joined:
                    return t
            elif ft in joined:
                return t
    return None


def _is_organic(record: Mapping[str, Any]) -> bool:
    if ORGANIC_LABELS & set(record.get("labels") or ()):
        return True
    names = " ".join(fold(record.get(k) or "") for k in ("name_fi", "name_sv", "name_en"))
    return "luomu" in names or "organic" in names or "ekologisk" in names


def _variant_words(asked_words: Sequence[str]) -> tuple[str, ...]:
    """The folded VARIANT_WORDS that count for this search: those the query or the heads ask for never do."""
    asked = [fold(q) for q in asked_words]
    return tuple(fv for fv in (fold(v) for v in VARIANT_WORDS) if not any(fv[:5] in a for a in asked))


def _variant(m: "HeadMatch", name_fi: str, variant_words: Sequence[str]) -> int:
    """0 for the plain product, more for a variant: a variant modifier in the head word ('annosmaito'), a processing
    or flavour word in the name ('leivitetty', 'suklaa'), or a head word in a coordination ('kermaviili ja sipuli')."""
    n = int(bool(m.modifier) and any(m.modifier.endswith(fold(v)) for v in VARIANT_MODIFIERS))
    words = [fold(w) for w in tokens(name_fi)]
    hit = any(w.startswith(v) or (len(v) >= 6 and v in w) for w in words for v in variant_words)
    return n + int(hit) + int(m.coordinated)


@dataclass
class _Plan:
    claims: list[str]
    banned: list[str]
    organic: bool
    temperature: str
    strict_may_contain: bool
    exclude: list[str]


def _check(record: Mapping[str, Any], plan: _Plan, why: list[str], warnings: list[str]) -> str | None:
    """None when the record passes every hard filter, else the reason it is dropped."""
    if record.get("placeholder"):
        return "placeholder"
    if plan.exclude and _excluded(record, plan.exclude):
        return "excluded_term"
    for claim in plan.claims:
        ok = has_claim(record, claim)
        if ok is None:
            return "claim_unknown"
        if not ok:
            if claim == "FREE_FROM_LACTOSE" and "LOW_LACTOSE" in (record.get("claims") or ()):
                return "low_lactose_only"  # X-24: vähälaktoosinen is not laktoositon
            return "claim_missing"
        why.append(f"claim {claim}")
    may: list[str] = []
    for code in plan.banned:
        status = allergen_status(record, code)
        if status == "unknown":
            return "allergens_unknown"  # never treated as safe (S-05)
        if status == "contains":
            return "allergen_contains"
        if status == "may_contain":
            if plan.strict_may_contain:
                return "allergen_may_contain"
            may.append(code)
    if plan.banned:
        why.append("declares none of " + ",".join(plan.banned))
    if may:
        warnings.append("may contain " + ",".join(may))
    if plan.temperature != "any":
        tc = record.get("temperature_class") or "unknown"
        if tc == "unknown":
            warnings.append("temperature class unknown")
        elif tc != plan.temperature:
            return "temperature"
    if plan.organic:
        if not _is_organic(record):
            return "not_organic"
        why.append("organic")
    flags = set(record.get("flags") or ())
    if "FREE_FROM_LACTOSE" in plan.claims:
        if "lactose_free_claim_with_lactose" in flags:
            warnings.append("lactose-free claim but lactose above 0.01 g/100 g")
        if "AM" in (record.get("allergens_contains") or ()) and "AM" not in plan.banned:
            warnings.append("lactose-free, but contains milk protein (AM): not milk-free")
    if "FREE_FROM_GLUTEN" in plan.claims and "gluten_free_with_oats" in flags and "GO" not in plan.banned:
        warnings.append("contains oats (GO), allowed by the buyer")
    if record.get("allergen_data") != "declared" and not plan.banned:
        warnings.append("allergen data unknown")
    if record.get("kind") == "minimal":
        warnings.append("minimal ERP record: no GS1 data")
    if (record.get("content") or {}).get("needs_review"):
        warnings.append("pack content needs review")
    return None


# ---- search ------------------------------------------------------------------------------------


def search(
    conn: sqlite3.Connection,
    query: str = "",
    heads: Iterable[str] = (),
    exclude: Iterable[str] = (),
    must_claims: Iterable[str] = (),
    must_not_allergens: Iterable[str] = (),
    temperature: str = "any",
    limit: int = DEFAULT_LIMIT,
    *,
    allow_oats: bool = False,
    strict_may_contain: bool = False,
    organic: bool | None = None,
) -> SearchResult:
    """Products for one need, best first. See the module docstring for the steps.

    allow_oats: the buyer accepts oats (GO) in gluten-free food; by default gluten-free excludes them (PLAN M4.3).
    strict_may_contain: drop MAY_CONTAIN of a banned allergen too; by default it is kept with a warning.
    organic: None reads it from the query ('luomu', 'organic'); True or False overrides.
    """
    query = _clean_text(query)
    head_terms, exclude_terms = _terms(heads), _terms(exclude)
    try:
        limit = max(1, min(MAX_LIMIT, int(limit)))
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    temperature = temperature if temperature in ("chilled", "frozen", "ambient") else "any"
    warnings: list[str] = []

    qw = read_query(query)
    claims = normalise_claims([*_terms(must_claims), *qw.claims])
    implied = [c for c in qw.claims if c not in normalise_claims(_terms(must_claims))]
    allergens, bad = normalise_allergens([*_terms(must_not_allergens), *qw.allergens])
    implied_allergens = [a for a in qw.allergens if a not in normalise_allergens(_terms(must_not_allergens))[0]]
    if bad:
        warnings.append("not GS1 allergen codes, not applied: " + ", ".join(bad))
    banned = expand_diet(claims, allergens)
    if allow_oats and "GO" not in allergens:
        banned = [c for c in banned if c != "GO"]
    plan = _Plan(
        claims=claims,
        banned=banned,
        organic=qw.organic if organic is None else bool(organic),
        temperature=temperature,
        strict_may_contain=strict_may_contain,
        exclude=exclude_terms,
    )

    parsed = parse_heads(head_terms)
    derived = False
    if not parsed and qw.content:
        names, _ = heads_from_query(qw.content)
        parsed, derived = parse_heads(names), True
    # Query words rank. A head the query names counts only when it is a specific form of another head
    # ('suodatinkahvi' with 'kahvi'), so that form comes first; every candidate already ends in some head, so the
    # generic head itself ('rahka') says nothing. Synonym words ('milk') are only translations of the heads.
    head_set = {h.word for h in parsed}

    def ranks(w: str) -> bool:
        if w in SYNONYMS:
            return False
        if w in head_set:
            return any(w != o and w.endswith(o) for o in head_set)
        return True

    bonus_words = [w for w in qw.content if ranks(w)]

    mode: Mode = "heads"
    expr = ""
    rows: list[Any] = []
    fuzzy: dict[str, float] = {}
    fts_failed = False
    if parsed:
        expr = head_match_expr(parsed)
        try:
            rows = _fts_rows(conn, expr)
        except sqlite3.Error:
            fts_failed = True
    if not rows and derived and qw.content and not fts_failed:
        mode, parsed = "text", []
        expr = text_match_expr(qw.content)
        try:
            rows = _fts_rows(conn, expr) or _fts_rows(conn, text_match_expr(qw.content, "OR"))
        except sqlite3.Error:
            fts_failed = True
    if not parsed and not qw.content and not fts_failed:
        warnings.append("no product type in the request: send heads or product words")
    elif not rows:
        mode = "fuzzy"
        target = " ".join(head_terms) or " ".join(qw.content)
        scored = _fuzzy_rows(conn, target) if target else []
        rows = [r for r, _ in scored]
        fuzzy = {r[1]: s for r, s in scored}
        if fts_failed:
            warnings.append("search index query failed; showing close spellings")
        elif rows:
            warnings.append("no exact name match; showing close spellings")

    dropped: Counter[str] = Counter()
    survivors: list[tuple[Hit, str, int, str]] = []  # hit, category, variant, the word that matched the head
    variant_words = _variant_words([*qw.content, *(w for h in parsed for w in (h.word, *h.before))])
    for r in rows:
        record = json.loads(r[3])
        why: list[str] = []
        hit_warnings: list[str] = []
        variant = 0
        m: HeadMatch | None = None
        if mode == "heads":
            found_head = match_head(record.get("name_fi") or "", parsed)
            if not isinstance(found_head, HeadMatch):
                dropped[found_head or "no_head_word"] += 1
                continue
            m = found_head
            why.append(f"head '{m.head.text}' in '{m.word}'")
        elif mode == "text":
            why.append("query words in the name")
        else:
            why.append(f"close spelling ({fuzzy.get(r[1], 0):.0f})")
        reason = _check(record, plan, why, hit_warnings)
        if reason:
            dropped[reason] += 1
            continue
        if m is not None:
            variant = _variant(m, record.get("name_fi") or "", variant_words)
        hit = Hit(product_id=r[1], record=record, why=why, warnings=hit_warnings, fuzzy_score=fuzzy.get(r[1]))
        survivors.append((hit, r[2], variant, fold(m.word) if m else ""))

    votes = Counter(cat for _, cat, _, _ in survivors)
    top_vote = max(votes.values(), default=0)
    # Word votes: a head word many survivors share ('maitorahka') is the usual form of the product; a word only one
    # has ('luumurahka') is usually a flavour or another product, so it ranks after the shared forms.
    word_votes = Counter(w for _, _, _, w in survivors if w)
    folded_bonus = [fold(w) for w in bonus_words]
    # A query word that is also a head counts only as a whole word or word start ('suodatinkahvi'), never inside a
    # compound: every candidate already ends in a head, so 'leipä' inside 'eväsleipä' says nothing.
    head_words = {h.folded for h in parsed}

    def key(item: tuple[Hit, str, int, str]) -> tuple:
        hit, cat, variant, word = item
        rec = hit.record
        names = [fold(w) for k in ("name_fi", "name_sv", "name_en", "brand") for w in tokens(rec.get(k) or "")]
        found = sum(
            1
            for b in folded_bonus
            if any(n.startswith(b) or (len(b) >= 4 and b not in head_words and b in n) for n in names)
        )
        major = votes[cat] * 3 >= top_vote  # a category at least a third the size of the largest one
        return (
            -found,
            -(hit.fuzzy_score or 0),
            not major,
            variant,
            bool(word) and word_votes[word] < 2 and len(word_votes) > 1,
            rec.get("kind") != "full",
            len(tokens(rec.get("name_fi") or "")),
            hit.product_id,
        )

    survivors.sort(key=key)
    hits = [h for h, _, _, _ in survivors[:limit]]
    interpretation: dict[str, Any] = {
        "mode": mode,
        "fts_match": expr,
        "heads": [h.text for h in parsed],
        "heads_from_query": derived,
        "ranking_words": bonus_words,
        "exclude": exclude_terms,
        "must_claims": claims,
        "implied_claims": implied,
        "implied_allergens": implied_allergens,
        "banned_allergens": banned,
        "allow_oats": allow_oats,
        "strict_may_contain": strict_may_contain,
        "organic": plan.organic,
        "temperature": temperature,
        "candidates": len(rows),
        "dropped": dict(sorted(dropped.items())),
        "category_votes": votes.most_common(5),
    }
    if implied:
        warnings.append("diet words in the query applied as claims: " + ", ".join(implied))
    if implied_allergens:
        warnings.append("allergen words in the query applied: " + ", ".join(implied_allergens))
    return SearchResult(
        hits=hits, total_matches=len(survivors), mode=mode, interpretation=interpretation, warnings=warnings
    )


# ---- golden-set evaluation (M4.5) --------------------------------------------------------------


def evaluate(conn: sqlite3.Connection, golden: Mapping[str, Any]) -> dict[str, Any]:
    """Precision@k of every judged query in a golden set, and every 'never' id that appeared.

    P@k is the share of the returned top k (at most k) that the judge accepted; a query that returns nothing while
    relevant products exist scores 0. 'never' ids are checked over the first MAX_LIMIT results, not only the top k.
    """
    k = int(golden.get("k", DEFAULT_LIMIT))
    rows: list[dict[str, Any]] = []
    for q in golden["queries"]:
        args = dict(q["args"])
        t0 = time.perf_counter()
        result = search(conn, **{**args, "limit": MAX_LIMIT})
        ms = (time.perf_counter() - t0) * 1000
        top = result.ids[:k]
        relevant = set(q.get("relevant") or ())
        hits = [i for i in top if i in relevant]
        scored = q.get("scored", True)
        precision = (len(hits) / len(top) if top else (1.0 if not relevant else 0.0)) if scored else None
        rows.append(
            {
                "id": q["id"],
                "lang": q.get("lang"),
                "held_out": bool(q.get("held_out")),
                "precision": precision,
                "returned": len(top),
                "total_matches": result.total_matches,
                "misses": [i for i in top if i not in relevant] if scored else [],
                "never_seen": sorted(set(result.ids) & set(q.get("never") or ())),
                "ms": round(ms, 1),
            }
        )

    def mean(xs: list[float]) -> float | None:
        return round(sum(xs) / len(xs), 4) if xs else None

    scored_rows = [r for r in rows if r["precision"] is not None]
    times = sorted(r["ms"] for r in rows)
    return {
        "k": k,
        "queries": rows,
        "precision": mean([r["precision"] for r in scored_rows]),
        "precision_tuned": mean([r["precision"] for r in scored_rows if not r["held_out"]]),
        "precision_held_out": mean([r["precision"] for r in scored_rows if r["held_out"]]),
        "precision_fi": mean([r["precision"] for r in scored_rows if r["lang"] == "fi"]),
        "precision_en": mean([r["precision"] for r in scored_rows if r["lang"] == "en"]),
        "never_violations": sum(len(r["never_seen"]) for r in rows),
        "ms_p50": times[len(times) // 2] if times else None,
        "ms_max": times[-1] if times else None,
    }
