/**
 * The dish form's logic (docs/basket-plan.md M27.3): the diet chips, the checks and the request they build.
 * Per B-13 the screen sends diet claims only, and the gateway expands them into allergen codes. Milk-free is the
 * one allergen the screen sends itself (AM): lactose-free food may still contain milk protein, so a lactose-free
 * claim never excludes milk.
 */
import type { BasketDish, BasketLine } from "../api";
import { basketTarget, type Allergen, type Claim, type PlanDishRequest } from "./intakeApi";

export type DietKey = "lactose_free" | "gluten_free" | "vegan" | "vegetarian" | "egg_free" | "milk_free";
export type Diet = { key: DietKey; label: string; claim: Claim | null; allergen: Allergen | null };

/** The chips, in the order their codes are sent. */
export const DIETS: readonly Diet[] = [
  { key: "lactose_free", label: "Lactose-free", claim: "FREE_FROM_LACTOSE", allergen: null },
  { key: "gluten_free", label: "Gluten-free", claim: "FREE_FROM_GLUTEN", allergen: null },
  { key: "vegan", label: "Vegan", claim: "VEGAN", allergen: null },
  { key: "vegetarian", label: "Vegetarian", claim: "VEGETARIAN", allergen: null },
  { key: "egg_free", label: "Egg-free", claim: "FREE_FROM_EGGS", allergen: null },
  { key: "milk_free", label: "Milk-free", claim: null, allergen: "AM" },
];

export const MAX_SERVINGS = 5000;
export const MAX_DISH_CHARS = 200;

/** What the form holds: the fields as typed, and the chips that are on. */
export type DishFormValues = { dish: string; servings: string; needDate: string; diets: readonly DietKey[] };
export type DishField = "dish" | "servings" | "needDate";
export type DishProblems = Partial<Record<DishField, string>>;

/** The date of the gateway's as-of time, "2026-11-14T10:00:00+02:00" giving "2026-11-14"; "" when there is none. */
export function dateOf(asOf: string): string {
  return /^(\d{4}-\d{2}-\d{2})/.exec(asOf.trim())?.[1] ?? "";
}

/** The servings as typed when they are a whole number from 1 to 5000, else null. */
export function servingsOf(text: string): number | null {
  const t = text.trim();
  if (!/^\d{1,5}$/.test(t)) return null;
  const n = Number(t);
  return n >= 1 && n <= MAX_SERVINGS ? n : null;
}

/** What to fix before the form can be sent, per field; empty when it can be sent. minDate "" sets no lower bound. */
export function dishProblems(values: DishFormValues, minDate: string): DishProblems {
  const problems: DishProblems = {};
  const dish = values.dish.trim();
  if (!dish) problems.dish = "Name the dish, for example mansikkakakku.";
  else if ([...dish].length > MAX_DISH_CHARS) problems.dish = `Use at most ${MAX_DISH_CHARS} characters for the dish.`;
  if (servingsOf(values.servings) === null) problems.servings = `Give the servings as a whole number from 1 to ${MAX_SERVINGS}.`;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(values.needDate)) problems.needDate = "Choose a delivery date.";
  else if (minDate && values.needDate < minDate) problems.needDate = `Choose a delivery date from ${minDate} on.`;
  return problems;
}

/**
 * The PlanDishRequest for checked values (dishProblems empty): claims in DIETS order, whatever order the chips were
 * pressed in, and milk-free as the allergen AM, never as a claim.
 */
export function buildDishRequest(values: DishFormValues, language: "fi" | "en", basketId: string | null): PlanDishRequest {
  const chosen = DIETS.filter((d) => values.diets.includes(d.key));
  return {
    dish: values.dish.trim(),
    servings: servingsOf(values.servings) ?? 0,
    need_date: values.needDate,
    must_claims: chosen.flatMap((d) => (d.claim ? [d.claim] : [])),
    must_not_allergens: chosen.flatMap((d) => (d.allergen ? [d.allergen] : [])),
    language,
    basket_id: basketTarget(basketId),
  };
}

/** The language the buyer speaks, for the dish request: Finnish when the browser says so, else English. */
export function buyerLanguage(languages: readonly string[] = globalThis.navigator?.languages ?? []): "fi" | "en" {
  return languages[0]?.toLowerCase().startsWith("fi") ? "fi" : "en";
}

/**
 * A planned dish as the basket card shows it (M27.2), from the gateway's BasketDish and the basket's lines: the
 * names, the servings and date, the batch note, the warnings (shown stronger) and the assumptions, and the dish's
 * lines that are still in the basket, with those that need the buyer. Nothing is computed but which lines remain.
 */
export type DishView = {
  name: string; nameFi: string | null; meta: string; batchNote: string; warnings: string[]; assumptions: string[];
  lineIds: number[]; openLineIds: number[]; removed: number;
};

export function dishView(d: BasketDish, lines: readonly Pick<BasketLine, "line_id" | "status">[] | null = null): DishView {
  const name = d.dish_name.en || d.dish_name.fi || d.dish;
  const nameFi = d.dish_name.fi && d.dish_name.fi !== name ? d.dish_name.fi : null;
  const present = lines === null ? d.line_ids : d.line_ids.filter((id) => lines.some((l) => l.line_id === id));
  const open = lines === null ? [] : present.filter((id) => lines.find((l) => l.line_id === id)?.status !== "priced");
  const n = present.length;
  const meta = `${d.servings} ${d.servings === 1 ? "serving" : "servings"} · delivery ${d.need_date} · ` +
    `${n} ${n === 1 ? "line" : "lines"} in the basket`;
  const text = (m: { en: string; fi: string }) => m.en || m.fi;
  return {
    name, nameFi, meta, batchNote: text(d.batch_note), warnings: d.warnings.map(text).filter(Boolean),
    assumptions: d.assumptions.map(text).filter(Boolean), lineIds: [...present].sort((a, b) => a - b),
    openLineIds: [...open].sort((a, b) => a - b), removed: d.line_ids.length - n,
  };
}
