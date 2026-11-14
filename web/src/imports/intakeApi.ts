/**
 * Gateway calls for the three ways to fill the basket from the screen (docs/basket-plan.md M25.5, M27.3, M28.4):
 * an Excel or CSV list, a photo of a list, and a dish. Every intake call lives here. api.ts's call() sends JSON
 * only, so uploads go through send() below, which leaves Content-Type to the browser (multipart/form-data with its
 * boundary) and sends the buyer cookie.
 *
 * Every failure becomes an IntakeError {status, message}: the gateway's own detail when it sent one, otherwise a
 * short sentence for that status. Status 0 means the gateway could not be reached.
 */
import type { DishResponse, ImportResponse } from "../api";

/** GS1 claims and allergen codes, exactly as Claim and Allergen in gateway/app/contract.py. */
export type Claim =
  | "FREE_FROM_LACTOSE" | "FREE_FROM_GLUTEN" | "VEGAN" | "VEGETARIAN" | "FREE_FROM_EGGS" | "FREE_FROM_SOY"
  | "FREE_FROM_WHEAT" | "LOW_LACTOSE";
export type Allergen =
  | "AM" | "AE" | "AW" | "UW" | "GB" | "NR" | "GO" | "AY" | "AN" | "AP" | "AS" | "AF" | "AC" | "UM" | "BC" | "BM"
  | "AU" | "NL";

/** POST /v1/baskets/dish: PlanDishRequest in gateway/app/contract.py. Flat; every field is always sent. */
export type PlanDishRequest = {
  dish: string;
  servings: number;
  need_date: string; // YYYY-MM-DD, Europe/Helsinki
  must_claims: Claim[];
  must_not_allergens: Allergen[];
  language: "fi" | "en"; // the language the buyer speaks
  basket_id: string; // the basket in focus, or "new"
};

export const INTAKE_PATHS = {
  sheet: "/v1/baskets/import",
  image: "/v1/baskets/import-image",
  dish: "/v1/baskets/dish",
} as const;
export type IntakeKind = keyof typeof INTAKE_PATHS;

export const TEMPLATE_XLSX = "/v1/baskets/template.xlsx";
export const TEMPLATE_CSV = "/tilauslista-pohja.csv"; // web/public

/** The basket_id an intake call sends: the basket in focus, or "new" to start one (B-03). */
export const basketTarget = (basketId: string | null): string => (basketId ? basketId : "new");

// The gateway's answers in the same words, so a refusal reads the same from the browser and from the gateway.
export const WRONG_SHEET_TYPE = "Use an Excel .xlsx file or a .csv file.";
export const OLD_XLS = "Old Excel .xls files cannot be read. Save the file as .xlsx or .csv and try again.";
export const SHEET_TOO_LARGE = "The file is over 1 MB. Split the list into smaller files.";
export const SHEET_UNREADABLE = "The file could not be read, or it has more than 200 rows.";
export const IMAGE_TOO_LARGE = "The photo is over 7.5 MB. Choose a smaller image.";
export const WRONG_IMAGE_TYPE = "Use a JPEG, PNG, WebP or GIF image.";
export const IMAGE_TOO_WIDE = "The image is too large: at most 8000 pixels per side.";
export const AI_UNAVAILABLE = "The AI service is unavailable right now. Try again in a moment.";
export const DISH_INVALID = "Check the dish name, the servings (1 to 5000) and the delivery date.";
export const SIGN_IN = "Please sign in first.";
export const BASKET_NOT_FOUND = "The basket was not found. Reload the page, or start a new basket.";
export const NETWORK = "Could not reach the gateway. Check the connection and try again.";
export const CANCELLED = "The request was cancelled.";
export const UNREADABLE_ANSWER = "The gateway sent an answer this page could not read. Reload the page and check the basket.";
export const GENERIC = "Something went wrong. Try again.";

const BY_KIND: Record<IntakeKind, Partial<Record<number, string>>> = {
  sheet: { 413: SHEET_TOO_LARGE, 415: WRONG_SHEET_TYPE, 422: SHEET_UNREADABLE },
  image: { 413: IMAGE_TOO_LARGE, 415: WRONG_IMAGE_TYPE, 422: IMAGE_TOO_WIDE, 503: AI_UNAVAILABLE },
  dish: { 422: DISH_INVALID, 503: AI_UNAVAILABLE },
};
const COMMON: Partial<Record<number, string>> = { 0: NETWORK, 401: SIGN_IN, 404: BASKET_NOT_FOUND };

export class IntakeError extends Error {
  override name = "IntakeError";
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

/** The sentence shown when the gateway sent no usable detail. */
export function fallbackMessage(kind: IntakeKind, status: number): string {
  const known = BY_KIND[kind][status] ?? COMMON[status];
  if (known) return known;
  if (status === 502 || status === 504) return `Could not reach the gateway (HTTP ${status}). Try again in a moment.`;
  if (status >= 500) return `The gateway hit an error (HTTP ${status}). Try again in a moment.`;
  return `The gateway refused the request (HTTP ${status}).`;
}

const clip = (s: string) => (s.length > 300 ? `${s.slice(0, 299)}…` : s);

/**
 * The gateway's detail from an error body: FastAPI's {detail: "..."}, or for a validation error the first item of
 * {detail: [{loc, msg}]} as "field: msg". Only the gateway's own words are used, never the echoed input.
 */
export function detailOf(body: unknown): string | null {
  if (typeof body !== "object" || body === null) return null;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail.trim() ? clip(detail.trim()) : null;
  if (Array.isArray(detail)) {
    const first = detail[0] as { loc?: unknown; msg?: unknown } | undefined;
    if (!first || typeof first.msg !== "string" || !first.msg.trim()) return null;
    const loc = Array.isArray(first.loc) ? first.loc.filter((p): p is string => typeof p === "string" && p !== "body") : [];
    const field = loc.at(-1);
    return clip(field ? `${field}: ${first.msg.trim()}` : first.msg.trim());
  }
  return null;
}

export function intakeError(kind: IntakeKind, status: number, detail: string | null): IntakeError {
  return new IntakeError(status, detail ?? fallbackMessage(kind, status));
}

/** Text for an error shown on screen: an IntakeError's own message, or a generic sentence. */
export const errorText = (e: unknown): string => (e instanceof IntakeError ? e.message : GENERIC);

async function send<T>(kind: IntakeKind, body: FormData | PlanDishRequest, signal?: AbortSignal): Promise<T> {
  const form = body instanceof FormData;
  let r: Response;
  try {
    r = await fetch(INTAKE_PATHS[kind], {
      method: "POST",
      credentials: "include",
      // No Content-Type with FormData: the browser writes multipart/form-data and its boundary itself.
      headers: form ? { Accept: "application/json" } : { Accept: "application/json", "Content-Type": "application/json" },
      body: form ? body : JSON.stringify(body),
      signal,
    });
  } catch {
    throw new IntakeError(0, signal?.aborted ? CANCELLED : NETWORK);
  }
  let json: unknown;
  try {
    json = await r.json();
  } catch {
    json = undefined; // an HTML error page from a proxy, or a cut connection
  }
  if (!r.ok) throw intakeError(kind, r.status, detailOf(json));
  if (typeof json !== "object" || json === null) throw new IntakeError(r.status, UNREADABLE_ANSWER);
  return json as T;
}

/** The multipart helper: POST a form (a file plus basket_id) to an intake route and get its typed answer. */
export function upload<T>(kind: "sheet" | "image", form: FormData, signal?: AbortSignal): Promise<T> {
  return send<T>(kind, form, signal);
}

/** POST /v1/baskets/import: an .xlsx or .csv list; every row becomes a basket line, matched and priced. */
export function importSheet(file: File, basketId: string, signal?: AbortSignal): Promise<ImportResponse> {
  const form = new FormData();
  form.append("basket_id", basketId);
  form.append("file", file, file.name);
  return upload<ImportResponse>("sheet", form, signal);
}

const EXTENSION: Record<string, string> = { "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif" };

/** POST /v1/baskets/import-image: one image of a list (normally downscaleToJpeg's JPEG); it is never stored. */
export function importImage(image: Blob, basketId: string, signal?: AbortSignal): Promise<ImportResponse> {
  const form = new FormData();
  form.append("basket_id", basketId);
  form.append("file", image, image instanceof File ? image.name : `photo.${EXTENSION[image.type] ?? "jpg"}`);
  return upload<ImportResponse>("image", form, signal);
}

/** POST /v1/baskets/dish: the gateway has the dish broken down and adds every ingredient as a basket line. */
export function planDish(request: PlanDishRequest, signal?: AbortSignal): Promise<DishResponse> {
  return send<DishResponse>("dish", request, signal);
}
