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
  line_net: string; vat_rate: string; line_vat: string; line_gross: string;
};
export type Quote = {
  quote_id: string; status: string; lines: QuoteLine[]; total_net: string; total_vat: string; total_gross: string;
  delivery_date: string; issued_at: string; expires_at: string; confirmed: boolean; quote_jws: string | null;
  evidence: { stub: boolean; api_time_now: string | null };
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
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method, credentials: "include",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const j = (await r.json()) as { detail?: unknown };
      if (typeof j.detail === "string") detail = j.detail;
    } catch { /* not JSON */ }
    throw new HttpError(r.status, detail);
  }
  return (await r.json()) as T;
}

export const api = {
  me: () => call<Me>("GET", "/api/me"),
  login: (buyer_id: "chef" | "head_chef") => call<Me>("POST", "/api/login", { buyer_id }),
  logout: () => fetch("/api/logout", { method: "POST", credentials: "include" }),
  agentSession: (mode: "webrtc" | "websocket") => call<Session>("POST", "/api/agent-session", { mode }),
  offerSet: (id: string) => call<OfferSet>("GET", `/v1/offers/${encodeURIComponent(id)}`),
  quote: (id: string) => call<Quote>("GET", `/v1/quotes/${encodeURIComponent(id)}`),
  confirm: (id: string) =>
    call<{ confirmed: boolean; confirmation_ref: string | null }>("POST", `/v1/quotes/${encodeURIComponent(id)}/confirm`),
  approval: (id: string) => call<Approval>("GET", `/v1/approvals/${encodeURIComponent(id)}`),
};

export const eur = (s: string) =>
  new Intl.NumberFormat("fi-FI", { style: "currency", currency: "EUR" }).format(Number(s));
export const helsinki = (iso: string) =>
  new Intl.DateTimeFormat("fi-FI", {
    timeZone: "Europe/Helsinki", weekday: "short", day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit",
  }).format(new Date(iso));
