import { describe, expect, it } from "vitest";
import { DIETS, buildDishRequest, buyerLanguage, dateOf, dishProblems, dishView, servingsOf, type DishFormValues } from "./dish";
import { dish, line, msg } from "./fixtures";

const form = (over: Partial<DishFormValues> = {}): DishFormValues => ({
  dish: "mansikkakakku", servings: "40", needDate: "2026-11-16", diets: [], ...over,
});

describe("the dish request", () => {
  it("sends the dish, the servings as a number, the date, the language and the basket", () => {
    expect(buildDishRequest(form({ dish: "  mansikkakakku " }), "fi", "B-0A1B2C3D4E")).toEqual({
      dish: "mansikkakakku", servings: 40, need_date: "2026-11-16", must_claims: [], must_not_allergens: [],
      language: "fi", basket_id: "B-0A1B2C3D4E",
    });
  });

  it("starts a new basket when none is in focus", () => {
    expect(buildDishRequest(form(), "en", null).basket_id).toBe("new");
  });

  it("sends each diet chip as its claim, in a fixed order whatever the order of the clicks", () => {
    const r = buildDishRequest(form({ diets: ["egg_free", "vegan", "lactose_free", "gluten_free", "vegetarian"] }), "fi", null);
    expect(r.must_claims).toEqual(["FREE_FROM_LACTOSE", "FREE_FROM_GLUTEN", "VEGAN", "VEGETARIAN", "FREE_FROM_EGGS"]);
    expect(r.must_not_allergens).toEqual([]); // the gateway expands the claims into allergen codes (B-13)
  });

  it("sends milk-free as the allergen AM, never as a claim", () => {
    const r = buildDishRequest(form({ diets: ["milk_free"] }), "fi", null);
    expect(r.must_claims).toEqual([]);
    expect(r.must_not_allergens).toEqual(["AM"]);
  });

  it("keeps lactose-free and milk-free apart: lactose-free alone never excludes milk", () => {
    expect(buildDishRequest(form({ diets: ["lactose_free"] }), "fi", null).must_not_allergens).toEqual([]);
    const both = buildDishRequest(form({ diets: ["milk_free", "lactose_free"] }), "fi", null);
    expect(both.must_claims).toEqual(["FREE_FROM_LACTOSE"]);
    expect(both.must_not_allergens).toEqual(["AM"]);
  });

  it("offers exactly the six chips of the plan, each with one code", () => {
    expect(DIETS.map((d) => d.label)).toEqual(["Lactose-free", "Gluten-free", "Vegan", "Vegetarian", "Egg-free", "Milk-free"]);
    for (const d of DIETS) expect((d.claim === null) !== (d.allergen === null)).toBe(true);
  });
});

describe("checks before sending", () => {
  it("passes a complete form", () => {
    expect(dishProblems(form(), "2026-11-14")).toEqual({});
  });

  it("asks for a dish name of at most 200 characters", () => {
    expect(dishProblems(form({ dish: "   " }), "").dish).toMatch(/Name the dish/);
    expect(dishProblems(form({ dish: "k".repeat(200) }), "").dish).toBeUndefined();
    expect(dishProblems(form({ dish: "k".repeat(201) }), "").dish).toMatch(/at most 200/);
    expect(dishProblems(form({ dish: "🍓".repeat(200) }), "").dish).toBeUndefined(); // counted as the gateway counts
  });

  it("takes whole servings from 1 to 5000 only", () => {
    expect(servingsOf("40")).toBe(40);
    expect(servingsOf(" 5000 ")).toBe(5000);
    expect(servingsOf("1")).toBe(1);
    for (const bad of ["", "0", "5001", "12.5", "1e3", "-4", "forty", "40 hlö"]) {
      expect(servingsOf(bad)).toBeNull();
      expect(dishProblems(form({ servings: bad }), "").servings).toMatch(/whole number from 1 to 5000/);
    }
  });

  it("asks for a delivery date no earlier than the gateway's as-of date", () => {
    expect(dishProblems(form({ needDate: "" }), "2026-11-14").needDate).toBe("Choose a delivery date.");
    expect(dishProblems(form({ needDate: "2026-11-13" }), "2026-11-14").needDate).toMatch(/from 2026-11-14 on/);
    expect(dishProblems(form({ needDate: "2026-11-14" }), "2026-11-14").needDate).toBeUndefined();
    expect(dishProblems(form({ needDate: "2020-01-01" }), "").needDate).toBeUndefined(); // no as-of: no lower bound
  });

  it("reads the date of the gateway's as-of time", () => {
    expect(dateOf("2026-11-14T10:00:00+02:00")).toBe("2026-11-14");
    expect(dateOf("2026-11-14")).toBe("2026-11-14");
    expect(dateOf("")).toBe("");
    expect(dateOf("14.11.2026")).toBe("");
  });
});

describe("the planned dish on the basket card", () => {
  it("shows the gateway's names, servings, date, batch note, warnings and assumptions", () => {
    const d = dish({ warnings: [msg("No lactose-free quark.")], assumptions: [msg("A sponge cake."), msg("", "")] });
    expect(dishView(d)).toEqual({
      name: "Strawberry cake", nameFi: "Mansikkakakku", meta: "40 servings · delivery 2026-11-16 · 3 lines in the basket",
      batchNote: "About 5 cakes of 8 portions.", warnings: ["No lactose-free quark."], assumptions: ["A sponge cake."],
      lineIds: [5, 6, 7], openLineIds: [], removed: 0,
    });
  });

  it("lists only the dish's lines still in the basket, and those that need the buyer", () => {
    const d = dish({ line_ids: [7, 5, 6] });
    const v = dishView(d, [line({ line_id: 5 }), line({ line_id: 7, status: "needs_choice" }), line({ line_id: 9 })]);
    expect(v.lineIds).toEqual([5, 7]);
    expect(v.openLineIds).toEqual([7]);
    expect(v.removed).toBe(1);
    expect(v.meta).toBe("40 servings · delivery 2026-11-16 · 2 lines in the basket");
  });

  it("falls back to the Finnish name or the dish as asked, and says 1 serving", () => {
    const v = dishView(dish({ dish_name: msg("", "Kakku"), servings: 1, line_ids: [1] }));
    expect(v.name).toBe("Kakku");
    expect(v.nameFi).toBeNull();
    expect(v.meta).toBe("1 serving · delivery 2026-11-16 · 1 line in the basket");
    expect(dishView(dish({ dish_name: msg("", "") })).name).toBe("mansikkakakku");
  });
});

describe("the buyer's language", () => {
  it("is Finnish only when the browser's first language is", () => {
    expect(buyerLanguage(["fi-FI", "en"])).toBe("fi");
    expect(buyerLanguage(["en-GB", "fi"])).toBe("en");
    expect(buyerLanguage([])).toBe("en");
  });
});
