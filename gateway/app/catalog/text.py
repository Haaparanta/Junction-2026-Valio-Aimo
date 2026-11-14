"""Name text for the search indexes (PLAN M4.1, findings S-01, S-04).

The catalogue build stores these forms so that search (M4) only queries:
- `name_tokens`: the casefolded fi name as space-separated word tokens, for whole-word checks in code;
- `reversed_tokens`: the same alphabetic tokens reversed, for an FTS5 prefix query that is a suffix match on the end of
  a Finnish compound word (`rev_fi:"otiam"*` finds every token ending in "maito");
- the raw names, which FTS5 itself folds with `unicode61 remove_diacritics 2` and the trigram tokenizer.

`reverse_term` turns a query head into the reversed form with the same normalisation, so a query never depends on how
the build tokenised.
"""

import re
import unicodedata

# Word characters without the underscore: letters (ä, ö, å included) and digits. Everything else separates tokens,
# including hyphens ("kana-annos" -> "kana", "annos"), registered marks and punctuation.
_TOKEN = re.compile(r"[^\W_]+")


def normalise(text: str | None) -> str:
    """NFC and casefold, keeping Finnish letters as they are (FTS5 does its own diacritic folding)."""
    if not text:
        return ""
    return unicodedata.normalize("NFC", text).casefold()


def tokens(text: str | None) -> list[str]:
    """Word tokens of a name, in order, casefolded."""
    return _TOKEN.findall(normalise(text))


def name_tokens(text: str | None) -> str:
    return " ".join(tokens(text))


def reversed_tokens(text: str | None) -> str:
    """Alphabetic tokens of two or more letters, each reversed: 'kevytmaitojuoma 1 l' -> 'amoujotiamytvek'.

    Numbers and one-letter unit words carry no product type, so they are left out of the suffix index.
    """
    return " ".join(t[::-1] for t in tokens(text) if len(t) >= 2 and t.isalpha())


def reverse_term(term: str) -> str:
    """A query head in the form `reversed_tokens` stores: 'Maito' -> 'otiam'. Multi-word input keeps the last word."""
    toks = tokens(term)
    return toks[-1][::-1] if toks else ""
