"""Diet expansion (docs/basket-plan.md B-13): the one place where diet claims become allergen exclusions.

The screen and the agent send claims only; the dish breakdown, the basket and search all call expand_diet,
so the rule lives here and the dish prompt's own diet rules are a second line of defence.
"""

from collections.abc import Iterable

# GS1 allergen codes each claim excludes. Claims that are not listed add nothing.
CLAIM_ALLERGENS: dict[str, tuple[str, ...]] = {
    # Wheat, cereals containing gluten, barley, rye, and oats: oats are excluded unless the buyer allows them
    # (PLAN M4.3, the safer default; docs/basket-plan.md section 6, question 1).
    "FREE_FROM_GLUTEN": ("UW", "AW", "GB", "NR", "GO"),
    "VEGAN": ("AM", "AE", "AF", "AC", "UM"),  # milk, egg, fish, crustaceans, molluscs
    "FREE_FROM_EGGS": ("AE",),
    "FREE_FROM_SOY": ("AY",),
    "FREE_FROM_WHEAT": ("UW",),
    # FREE_FROM_LACTOSE and LOW_LACTOSE add nothing: lactose-free dairy still contains milk protein, so a
    # lactose-free request never excludes AM. Only a milk-free request or a milk allergy sends AM itself.
}


# Names for messages to the buyer, (fi, en). The codes are the contract's Claim and Allergen literals.
CLAIM_NAMES: dict[str, tuple[str, str]] = {
    "FREE_FROM_LACTOSE": ("laktoositon", "lactose-free"),
    "FREE_FROM_GLUTEN": ("gluteeniton", "gluten-free"),
    "VEGAN": ("vegaaninen", "vegan"),
    "VEGETARIAN": ("kasvis", "vegetarian"),
    "FREE_FROM_EGGS": ("munaton", "egg-free"),
    "FREE_FROM_SOY": ("soijaton", "soy-free"),
    "FREE_FROM_WHEAT": ("vehnätön", "wheat-free"),
    "LOW_LACTOSE": ("vähälaktoosinen", "low-lactose"),
}
ALLERGEN_NAMES: dict[str, tuple[str, str]] = {
    "AM": ("maito", "milk"),
    "AE": ("kananmuna", "egg"),
    "AW": ("gluteenia sisältävät viljat", "cereals containing gluten"),
    "UW": ("vehnä", "wheat"),
    "GB": ("ohra", "barley"),
    "NR": ("ruis", "rye"),
    "GO": ("kaura", "oats"),
    "AY": ("soija", "soy"),
    "AN": ("pähkinät", "tree nuts"),
    "AP": ("maapähkinä", "peanut"),
    "AS": ("seesami", "sesame"),
    "AF": ("kala", "fish"),
    "AC": ("äyriäiset", "crustaceans"),
    "UM": ("nilviäiset", "molluscs"),
    "BC": ("selleri", "celery"),
    "BM": ("sinappi", "mustard"),
    "AU": ("sulfiitit", "sulphites"),
    "NL": ("lupiini", "lupin"),
}


def expand_diet(claims: Iterable[str], allergens: Iterable[str]) -> list[str]:
    """The allergen codes no product may contain: the buyer's own codes plus those their claims imply.

    Sorted and without duplicates, so the result can be compared and stored as is.
    """
    codes = set(allergens)
    for claim in claims:
        codes.update(CLAIM_ALLERGENS.get(claim, ()))
    return sorted(codes)
