/** Gateway client. Every on-screen number comes from these responses, fetched by id. */
export type Msg = { fi: string; en: string };
export type Me = { buyer_id: string; display_name: string; org_id: string; role: string; order_cap_eur: string; as_of: string };
export type Offer = {
  offer_id: string; tier: "best" | "better" | "good" | "other"; product_id: string; name_fi: string; api_unit: string;
  qty: number; content_total: string; unit_price_net: string; total_net: string; price_per_base_unit: string;
  base_unit: string; delivery_date: string; order_by: string; stock: string; stock_qty: number | null; flags: string[];
  explanation: Msg;
};
export type NotOffered = { product_id: string; name_fi: string; flags: string[]; reason: Msg };
export type OfferSet = {
  status: string; offer_set_id: string; as_of: string; options: Offer[]; not_offered: NotOffered[];
  counts: Record<string, number>; message_for_user: Msg; warnings: string[];
};
export type QuoteLine = {
  line_id: number; product_id: string; name_fi: string; api_unit: string; qty: number; unit_price_net: string;
  line_net: string; vat_rate: string; line_vat: string; line_gross: string; delivery_date: string;
};
export type Quote = {
  quote_id: string; status: string; lines: QuoteLine[]; total_net: string; total_vat: string; total_gross: string;
  delivery_date: string; basket_id: string | null; basket_version: number | null; issued_at: string;
  expires_at: string; confirmed: boolean; quote_jws: string | null;
  evidence: { stub: boolean; api_time_now: string | null };
};

// ---- Basket, imports and dishes (docs/basket-plan.md). Mirrors gateway/app/contract.py. ----
export type Envelope = { status: string; reason_code: string | null; message_for_user: Msg; warnings: string[] };
export type Unit = "L" | "KG" | "PCS";
export type ContentPerUnit = { value: string; unit: Unit; source: string; confidence: "high" | "medium" | "low" };
export type ProductSummary = {
  product_id: string; name_fi: string; name_en: string | null; brand: string | null; vendor: string | null;
  category: string; sales_unit: string; content_per_unit: ContentPerUnit | null; claims: string[];
  allergens_contains: string[]; allergen_data: "declared" | "unknown";
  temperature_class: "chilled" | "frozen" | "ambient" | "unknown";
};
export type ProductResponse = Envelope & { product: ProductSummary };
export type ConfirmResponse = Envelope & { quote_id: string; confirmed: boolean; confirmation_ref: string | null };
export type OrderResponse = Envelope & {
  order_id: string | null; approval_id: string | null; approval_url: string | null; total_net: string | null;
};
export type LineSource = "voice" | "ui" | "import" | "image" | "dish";
export type LineStatus = "priced" | "needs_choice" | "needs_amount" | "unmatched" | "not_deliverable" | "cutoff_passed";
export type Confidence = "high" | "medium" | "low";
export type FlagNote = { code: string; text: Msg };
export type BasketLine = {
  line_id: number; source: LineSource; need_text: string; raw_text: string | null; confidence: Confidence | null;
  product_id: string | null; name_fi: string | null; amount: number | null; unit: Unit | null; need_date: string;
  offer: Offer | null; alternatives: Offer[]; status: LineStatus; flags: string[]; flag_notes: FlagNote[];
  message: Msg; overshoot: string | null; vat_rate: string | null; line_vat: string | null; line_gross: string | null;
  notes: Msg[];
};
export type BasketDish = {
  dish: string; dish_name: Msg; servings: number; need_date: string; batch_note: Msg; line_ids: number[];
  assumptions: Msg[]; warnings: Msg[];
};
export type Basket = {
  basket_id: string; buyer_id: string; status: "open" | "ordered"; version: number; lines: BasketLine[];
  counts: Record<string, number>; total_net: string; total_vat: string; total_gross: string; quote_id: string;
  quote_stale: boolean; dishes: BasketDish[]; dish_jobs: string[]; created_at: string; updated_at: string;
};
/** PATCH body for a line: 0 and "" mean "keep the current value" (flat schema, no optional fields). */
export type BasketLinePatch = { amount: number; unit: "" | Unit; need_date: string; offer_id: string };
export type BasketResponse = Envelope & { basket_id: string; basket: Basket; line: BasketLine | null };
export type BasketQuoteResponse = Envelope & {
  basket_id: string; quote_id: string | null; quote: Quote | null; total_net: string | null;
  total_gross: string | null; expires_at: string | null; open_lines: number[];
};
export type ImportRow = {
  row_number: number; status: LineStatus | "invalid"; message: Msg; line_id: number | null; raw_text: string;
};
export type ListItem = {
  raw_text: string; name: string; quantity: number | null; unit: Unit | null; note: string; confidence: Confidence;
};
export type ListExtraction = { items: ListItem[]; handwritten: boolean; unreadable: string[] };
export type ImportResponse = Envelope & {
  basket_id: string; basket: Basket; rows: ImportRow[]; counts: Record<string, number>;
  extraction: ListExtraction | null;
};
/** dish is null when Claude refused or found no ingredients (reason_code not_found). */
export type DishResponse = Envelope & { basket_id: string; basket: Basket; dish: BasketDish | null };
export type DishJobState = "pending" | "running" | "done" | "failed";
/** plan_dish (voice) answers at once; the open page runs the job and polls it (Claude needs 35-51 s). */
export type DishJobResponse = Envelope & {
  job_id: string; basket_id: string; state: DishJobState; result: DishResponse | null;
};
export type Approval = {
  status: string; approval_id: string; message_for_user: Msg;
  approval: { approval_id: string; status: string; order_id: string; quote_id: string; reasons: string[]; decide_by: string; approver_role: string };
};
export type Session = {
  mode: "webrtc" | "websocket"; conversation_token: string | null; signed_url: string | null;
  conversation_id: string | null; session_token: string; user_id: string; expires_in: number;
};

export class HttpError extends Error {
  /** `body` is the parsed JSON error body, when there was one (it may carry a reason_code). */
  constructor(public status: number, message: string, public body: unknown = null) {
    super(message);
  }
}

/** The text to show for a failed call: the gateway's own message when it sent one. */
export function errorDetail(j: unknown, fallback: string): string {
  if (!j || typeof j !== "object") return fallback;
  const o = j as { detail?: unknown; message_for_user?: { en?: unknown } };
  if (typeof o.message_for_user?.en === "string") return o.message_for_user.en;
  if (typeof o.detail === "string") return o.detail;
  const first = Array.isArray(o.detail) ? (o.detail[0] as { msg?: unknown } | undefined) : undefined;
  return typeof first?.msg === "string" ? first.msg : fallback; // FastAPI validation errors
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method, credentials: "include",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    let j: unknown = null;
    try {
      j = await r.json();
    } catch { /* not JSON */ }
    throw new HttpError(r.status, errorDetail(j, r.statusText || `HTTP ${r.status}`), j);
  }
  return (await r.json()) as T;
}

const seg = encodeURIComponent;
/** Line ids are integers from the gateway; anything else becomes 0, which the gateway refuses. */
const lineSeg = (lineId: number) => String(Number.isInteger(lineId) && lineId > 0 ? lineId : 0);
const linePath = (basketId: string, lineId: number) => `/v1/baskets/${seg(basketId)}/lines/${lineSeg(lineId)}`;

export const api = {
  me: () => call<Me>("GET", "/api/me"),
  login: (buyer_id: "chef" | "head_chef") => call<Me>("POST", "/api/login", { buyer_id }),
  logout: () => fetch("/api/logout", { method: "POST", credentials: "include" }),
  agentSession: (mode: "webrtc" | "websocket") => call<Session>("POST", "/api/agent-session", { mode }),
  offerSet: (id: string) => call<OfferSet>("GET", `/v1/offers/${seg(id)}`),
  product: (productId: string) => call<ProductResponse>("GET", `/v1/products/${seg(productId)}`),
  quote: (id: string) => call<Quote>("GET", `/v1/quotes/${seg(id)}`),
  /** The on-screen Confirm, under the buyer's own web session. reason_code quote_stale: the basket changed. */
  confirm: (id: string) => call<ConfirmResponse>("POST", `/v1/quotes/${seg(id)}/confirm`),
  /** Only when no call is running: during a call the agent places the order (two callers, two orders). */
  placeOrder: (quoteId: string) => call<OrderResponse>("POST", "/v1/orders", { quote_id: quoteId }),
  approval: (id: string) => call<Approval>("GET", `/v1/approvals/${seg(id)}`),

  // ---- the basket (docs/basket-plan.md M22-M24) ----
  basket: (basketId: string) => call<BasketResponse>("GET", `/v1/baskets/${seg(basketId)}`),
  /** The signed-in buyer's newest open basket, or null when there is none (HTTP 404). */
  currentBasket: async (): Promise<BasketResponse | null> => {
    try {
      return await call<BasketResponse>("GET", "/v1/baskets/current");
    } catch (e) {
      if (e instanceof HttpError && e.status === 404) return null;
      throw e;
    }
  },
  /** Send all four fields: 0 and "" keep the current value. The gateway prices the line again. */
  patchLine: (basketId: string, lineId: number, patch: BasketLinePatch) =>
    call<BasketResponse>("PATCH", linePath(basketId, lineId), patch),
  removeLine: (basketId: string, lineId: number) => call<BasketResponse>("DELETE", linePath(basketId, lineId)),
  restoreLine: (basketId: string, lineId: number) =>
    call<BasketResponse>("POST", `${linePath(basketId, lineId)}/restore`),
  /** An option card's offer into the basket in focus (null starts a new one); replaceLineId 0 adds a line. */
  addFromOffer: (basketId: string | null, offerId: string, replaceLineId = 0) =>
    call<BasketResponse>("POST", `/v1/baskets/${seg(basketId ?? "new")}/lines/from-offer`, {
      offer_id: offerId, replace_line_id: Number.isInteger(replaceLineId) && replaceLineId > 0 ? replaceLineId : 0,
    }),
  /** One quote for the whole basket. reason_code basket_incomplete: resolve open_lines first. */
  quoteBasket: (basketId: string) => call<BasketQuoteResponse>("POST", "/v1/baskets/quote", { basket_id: basketId }),
};

/** A short message for a thrown error. */
export const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

export const eur = (s: string) =>
  new Intl.NumberFormat("fi-FI", { style: "currency", currency: "EUR" }).format(Number(s));
export const helsinki = (iso: string) =>
  new Intl.DateTimeFormat("fi-FI", {
    timeZone: "Europe/Helsinki", weekday: "short", day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit",
  }).format(new Date(iso));
