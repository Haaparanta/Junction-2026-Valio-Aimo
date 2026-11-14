"""The checks in code after the dish breakdown call (docs/basket-plan.md B-12): the LLM plans, the gateway decides.

finalize_breakdown turns Claude's DishBreakdown into one the basket can trust:
* dish and servings echo the input, and every ingredient's need_date is the input's need_date;
* every ingredient excludes at least the allergens the input's diet needs imply (diet.expand_diet);
* search.limit is clamped to 1..25; amounts are rounded to 3 decimals and an ingredient whose amount is then not
  positive is dropped; per_serving is recomputed as amount / servings;
* a repeated ingredient_id is merged into the first one when the unit is the same (the amounts are added) and
  renamed when it is not;
* at most MAX_INGREDIENTS ingredients; empty heads fall back to the last word of the query.

Every dropped or changed diet need, and every dropped or merged ingredient, adds a warning {fi, en}. Claude's own
warnings are kept, first and unchanged: no warning is ever removed. Extra fields, such as a price, never get this
far: the DishBreakdown model forbids them.
"""

import math

from .contract import DishBreakdown, DishIngredient, DishInput, DishSearch, Msg
from .diet import ALLERGEN_NAMES, CLAIM_NAMES, expand_diet

MAX_INGREDIENTS = 40
LIMIT_MIN, LIMIT_MAX = 1, 25
DECIMALS = 3
_PUNCTUATION = ".,;:!?()[]\"'"


def finalize_breakdown(inp: DishInput, out: DishBreakdown) -> DishBreakdown:
    warnings = list(out.warnings)
    if out.servings != inp.servings:
        warnings.append(
            Msg(
                fi=f"Suunnitelma laskettiin {out.servings} annokselle, vaikka pyydettiin {inp.servings}; "
                "tarkista määrät.",
                en=f"The plan was worked out for {out.servings} servings, but {inp.servings} were asked for; "
                "check the amounts.",
            )
        )

    kept: list[DishIngredient] = []
    by_id: dict[str, int] = {}  # ingredient_id -> its place in kept
    for n, ing in enumerate(out.ingredients, start=1):
        fi, en = _names(ing)
        amount = round(ing.amount, DECIMALS)
        if not math.isfinite(amount) or amount <= 0:
            warnings.append(
                Msg(
                    fi=f"{fi}: määrä puuttui, joten aines jätettiin pois.",
                    en=f"{en}: no amount was given, so the ingredient was left out.",
                )
            )
            continue
        iid = ing.ingredient_id.strip().lower() or f"aines-{n}"
        ing = ing.model_copy(
            update={"ingredient_id": iid, "amount": amount, "need_date": inp.need_date, "search": _search(ing)}
        )
        if iid in by_id:
            first = kept[by_id[iid]]
            if first.unit == ing.unit:
                kept[by_id[iid]] = _merge(first, ing)
                warnings.append(
                    Msg(
                        fi=f"{fi} oli suunnitelmassa kahdesti; määrät laskettiin yhteen.",
                        en=f"{en} was in the plan twice; the amounts were added together.",
                    )
                )
                continue
            iid = _unique(iid, by_id)
            ing = ing.model_copy(update={"ingredient_id": iid})
            warnings.append(
                Msg(
                    fi=f"{fi} oli suunnitelmassa kahdesti eri yksiköillä; molemmat rivit pidettiin.",
                    en=f"{en} was in the plan twice with different units; both lines were kept.",
                )
            )
        by_id[iid] = len(kept)
        kept.append(ing)

    if len(kept) > MAX_INGREDIENTS:
        dropped = [_names(i) for i in kept[MAX_INGREDIENTS:]]
        kept = kept[:MAX_INGREDIENTS]
        warnings.append(
            Msg(
                fi=f"Aineksia oli yli {MAX_INGREDIENTS}; pois jätettiin: {', '.join(n[0] for n in dropped)}.",
                en=f"There were more than {MAX_INGREDIENTS} ingredients; left out: {', '.join(n[1] for n in dropped)}.",
            )
        )

    # The input's diet needs, as allergen codes, on every ingredient. Codes Claude added itself are kept: an extra
    # exclusion can only narrow the search, never make it unsafe.
    required = set(expand_diet(inp.must_claims, inp.must_not_allergens))
    added: set[str] = set()
    changed: list[tuple[str, str]] = []
    for k, ing in enumerate(kept):
        missing = required - set(ing.search.must_not_allergens)
        if missing:
            search = ing.search.model_copy(
                update={"must_not_allergens": sorted(required | set(ing.search.must_not_allergens))}
            )
            ing = ing.model_copy(update={"search": search})
            added |= missing
            changed.append(_names(ing))
        kept[k] = ing.model_copy(update={"per_serving": round(ing.amount / inp.servings, DECIMALS)})
    if changed:
        codes = sorted(added)
        fi_codes = ", ".join(ALLERGEN_NAMES[c][0] for c in codes)
        en_codes = ", ".join(ALLERGEN_NAMES[c][1] for c in codes)
        if len(changed) == len(kept):  # e.g. VEGAN, whose codes the prompt leaves to the gateway (B-13)
            msg = Msg(
                fi=f"Allergeenirajaus ({fi_codes}) lisättiin kaikille aineksille.",
                en=f"Allergen exclusions ({en_codes}) were added to every ingredient.",
            )
        else:
            msg = Msg(
                fi=f"Allergeenirajaus ({fi_codes}) lisättiin aineksille: {', '.join(n[0] for n in changed)}.",
                en=f"Allergen exclusions ({en_codes}) were added to: {', '.join(n[1] for n in changed)}.",
            )
        warnings.append(msg)

    # A claim may be left off an ingredient it does not apply to (FREE_FROM_LACTOSE on sugar), but not off them all.
    if kept:
        for claim in dict.fromkeys(inp.must_claims):
            if not any(claim in ing.search.must_claims for ing in kept):
                fi, en = CLAIM_NAMES[claim]
                warnings.append(
                    Msg(
                        fi=f"Ruokavaliotoive {fi} puuttui kaikista aineksista; tarkista tuotteet.",
                        en=f"The diet need {en} was missing from every ingredient; check the products.",
                    )
                )

    if not kept and not warnings:
        warnings.append(
            Msg(
                fi="Ruokalajista ei saatu aineksia. Kerro tarkemmin, mikä ruokalaji on.",
                en="No ingredients came out for this dish. Please say more about what the dish is.",
            )
        )

    return out.model_copy(
        update={"dish": inp.dish, "servings": inp.servings, "ingredients": kept, "warnings": warnings}
    )


def _names(ing: DishIngredient) -> tuple[str, str]:
    fi = ing.name.fi.strip() or ing.ingredient_id.strip() or "?"
    return fi, ing.name.en.strip() or fi


def _search(ing: DishIngredient) -> DishSearch:
    s = ing.search
    # search_products needs a query, and its heads match the end of the product name.
    query = s.query.strip() or ing.name.fi.strip() or ing.name.en.strip() or ing.ingredient_id.strip()
    heads = [h.strip() for h in s.heads if h.strip()]
    if not heads and query:
        heads = [query.split()[-1].strip(_PUNCTUATION).lower() or query.lower()]
    return s.model_copy(update={"query": query, "heads": heads, "limit": min(max(s.limit, LIMIT_MIN), LIMIT_MAX)})


def _merge(a: DishIngredient, b: DishIngredient) -> DishIngredient:
    """b is the same purchasable item as a in the same unit: add the amounts and keep every search restriction."""
    s = a.search.model_copy(
        update={
            "heads": _union(a.search.heads, b.search.heads),
            "exclude": _union(a.search.exclude, b.search.exclude),
            "must_claims": _union(a.search.must_claims, b.search.must_claims),
            "must_not_allergens": sorted(set(a.search.must_not_allergens) | set(b.search.must_not_allergens)),
        }
    )
    notes = list({(m.fi, m.en): m for m in [*a.notes, *b.notes]}.values())
    return a.model_copy(update={"amount": round(a.amount + b.amount, DECIMALS), "search": s, "notes": notes})


def _union[T](a: list[T], b: list[T]) -> list[T]:
    return list(dict.fromkeys([*a, *b]))


def _unique(iid: str, taken: dict[str, int]) -> str:
    n = 2
    while f"{iid}-{n}" in taken:
        n += 1
    return f"{iid}-{n}"
