/** A tiny external store: SDK callbacks write here, components subscribe with selectors (no per-frame renders). */
import { useSyncExternalStore } from "react";
import type { Basket, ImportResponse, Msg } from "../api";
import { isFinal, type DishJob } from "./dishJobs";

export type Persona = "aino" | "cow";
export type Transport = "webrtc" | "relay" | "websocket" | "text";
export type Turn = { id: string; role: "user" | "agent"; text: string; final: boolean };
export type GatewayOutcome = { tool: string; status: string; reasonCode: string | null; at: number };
/** "Replace line N": the option cards on screen are for this line of this basket (show_products line_id). */
export type ReplaceLine = { basketId: string; lineId: number };
/** One button on the toast, such as Undo. It belongs to the toast text it was shown with. */
export type ToastAction = { text: string; label: string; run: () => void };
/** An order the screen placed itself (no call running); during a call the agent places it. */
export type PlacedOrder = { quoteId: string; orderId: string | null; status: string; message: Msg };
/** Lines that stopped quote_basket (basket_incomplete), with the gateway's message. */
export type BasketAlert = { basketId: string; lines: number[]; message: string };
/** The latest list or photo import, shown under the basket card it went into (ImportSummary). */
export type IntakeResult = { basketId: string; kind: "sheet" | "photo"; response: ImportResponse };

export type Ui = {
  phase: "idle" | "connecting" | "live" | "error";
  transport: Transport | null;
  conversationId: string | null;
  mode: "speaking" | "listening";
  userSpeaking: boolean;
  pendingTools: Record<string, { tool: string; since: number }>;
  turns: Turn[];
  toast: string | null;
  toastAction: ToastAction | null;
  lastError: string | null;
  lastOutcome: GatewayOutcome | null;
  queue: "waiting" | "admitted" | "timed_out" | null;
  persona: Persona;
  offerSetId: string | null;
  basketId: string | null; // the basket in focus (B-03)
  basket: Basket | null; // the latest gateway answer for basketId, newest version wins
  replaceLine: ReplaceLine | null;
  basketAlert: BasketAlert | null;
  intake: IntakeResult | null;
  dishJobs: Record<string, DishJob>; // plan_dish jobs this page runs or watches, by job id
  quoteId: string | null;
  quoteBasketId: string | null; // the basket the quote on screen is for; null for a single-offer quote
  approvalId: string | null;
  confirmQuoteId: string | null;
  order: PlacedOrder | null;
  queuedText: string | null; // typed before a chat connected: sent on connect
};

export const initialUi: Ui = {
  phase: "idle", transport: null, conversationId: null, mode: "listening", userSpeaking: false, pendingTools: {},
  turns: [], toast: null, toastAction: null, lastError: null, lastOutcome: null, queue: null, persona: "aino",
  offerSetId: null, basketId: null, basket: null, replaceLine: null, basketAlert: null, intake: null, dishJobs: {}, quoteId: null,
  quoteBasketId: null, approvalId: null, confirmQuoteId: null, order: null, queuedText: null,
};

type Listener = () => void;

export function createStore<T>(initial: T) {
  let state = initial;
  const listeners = new Set<Listener>();
  return {
    get: () => state,
    set(patch: Partial<T> | ((s: T) => Partial<T>)) {
      const next = typeof patch === "function" ? patch(state) : patch;
      state = { ...state, ...next };
      listeners.forEach((l) => l());
    },
    subscribe(l: Listener) {
      listeners.add(l);
      return () => listeners.delete(l);
    },
  };
}

export const ui = createStore<Ui>(initialUi);

export function useUi<S>(select: (s: Ui) => S): S {
  return useSyncExternalStore(ui.subscribe, () => select(ui.get()));
}

const MAX_TURNS = 8;

export function upsertTurn(turns: Turn[], id: string, role: Turn["role"], update: (t: Turn) => Turn): Turn[] {
  const i = turns.findIndex((t) => t.id === id);
  if (i === -1) return [...turns, update({ id, role, text: "", final: false })].slice(-MAX_TURNS);
  const copy = turns.slice();
  copy[i] = update(copy[i] as Turn);
  return copy;
}

// ---- store updates (pure: they return a patch for ui.set) ----

/**
 * Put a basket in focus (null: none, the next add starts a new one). Switching baskets drops the quote,
 * the confirmation and the order that belonged to another basket. `basket` is the gateway's answer, when the
 * caller has one: an older version never replaces a newer one.
 */
export function focusBasket(s: Ui, basketId: string | null, basket: Basket | null = null): Partial<Ui> {
  const next: Partial<Ui> = {};
  if (s.basketId !== basketId) {
    const quoteIsForIt = s.quoteId !== null && basketId !== null && s.quoteBasketId === basketId;
    Object.assign(next, { basketId, basket: null, replaceLine: null, basketAlert: null });
    if (!quoteIsForIt) Object.assign(next, { quoteId: null, quoteBasketId: null, confirmQuoteId: null, order: null });
  }
  if (basket && basketId !== null && basket.basket_id === basketId) {
    const current = s.basketId === basketId ? s.basket : null;
    if (!current || current.basket_id !== basketId || current.version <= basket.version) next.basket = basket;
  }
  return next;
}

/**
 * A list or photo import went into basket `r.basket_id`: that basket comes into focus with the gateway's answer, and
 * the summary shows under it. A photo that gave no rows only puts its basket in focus when one already was.
 */
export function receiveImport(s: Ui, kind: IntakeResult["kind"], r: ImportResponse): Partial<Ui> {
  if (kind === "photo" && !(Array.isArray(r.rows) && r.rows.length > 0) && s.basketId === null) return {};
  return { ...focusBasket(s, r.basket_id, r.basket), intake: { basketId: r.basket_id, kind, response: r } };
}

/** The import summary to show for the basket in focus, if any. */
export const intakeOf = (s: Pick<Ui, "intake" | "basketId">): IntakeResult | null =>
  s.intake && s.intake.basketId === s.basketId ? s.intake : null;

/** A dish job's new state; whether it was announced to the agent is kept. */
export function putJob(s: Pick<Ui, "dishJobs">, j: DishJob): Partial<Ui> {
  const announced = s.dishJobs[j.jobId]?.announced ?? false;
  return { dishJobs: { ...s.dishJobs, [j.jobId]: { ...j, announced: j.announced || announced } } };
}

/** The job's final state has been told to the agent (or there was no call to tell). */
export function markAnnounced(s: Pick<Ui, "dishJobs">, jobId: string): Partial<Ui> {
  const j = s.dishJobs[jobId];
  return j && !j.announced ? { dishJobs: { ...s.dishJobs, [jobId]: { ...j, announced: true } } } : {};
}

/** The buyer closed a failed job's message. */
export function dismissJob(s: Pick<Ui, "dishJobs">, jobId: string): Partial<Ui> {
  if (!s.dishJobs[jobId]) return {};
  const { [jobId]: _gone, ...rest } = s.dishJobs;
  return { dishJobs: rest };
}

/** A finished job's message for the basket card: a failure, or a plan with no dish (Claude refused or found nothing). */
export type JobNotice = { jobId: string; text: string };

/**
 * What the basket card says about dish jobs: planning while the basket lists a job this page has not finished
 * (dish_jobs) or one of its jobs is still running; and a notice for each job that failed or planned no dish.
 */
export function jobsForBasket(
  jobs: Record<string, DishJob>, b: Pick<Basket, "basket_id" | "dish_jobs"> | null,
): { planning: boolean; notices: JobNotice[] } {
  if (!b) return { planning: false, notices: [] };
  const listed = Array.isArray(b.dish_jobs) ? b.dish_jobs : [];
  const mine = Object.values(jobs).filter((j) => j.basketId === b.basket_id);
  const planning = listed.some((id) => !jobs[id] || !isFinal(jobs[id])) || mine.some((j) => !isFinal(j));
  const notices = mine.flatMap((j): JobNotice[] => {
    if (j.phase === "failed") return [{ jobId: j.jobId, text: j.message }];
    if (j.phase === "done" && j.result && !j.result.dish) {
      return [{ jobId: j.jobId, text: j.result.message_for_user.en || j.message || "No dish was planned." }];
    }
    return [];
  });
  return { planning, notices };
}

/** A gateway answer for the basket in focus; answers for any other basket are ignored. */
export function receiveBasket(s: Ui, basket: Basket): Partial<Ui> {
  return s.basketId === basket.basket_id ? focusBasket(s, basket.basket_id, basket) : {};
}

/**
 * Show a quote (show_quote, request_buyer_confirmation, or the basket card's own quote). `basketId` is the
 * basket it was made for, when known; otherwise the basket in focus is the best guess until the quote loads.
 */
export function showQuote(s: Ui, quoteId: string, basketId?: string | null): Partial<Ui> {
  if (s.quoteId === quoteId) return basketId === undefined ? {} : { quoteBasketId: basketId };
  return { quoteId, quoteBasketId: basketId === undefined ? s.basketId : basketId, order: null };
}

/** The quote card loaded its quote: remember its basket, and show that basket when none is in focus. */
export function quoteLoaded(s: Ui, q: { quote_id: string; basket_id: string | null }): Partial<Ui> {
  if (s.quoteId !== q.quote_id) return {};
  const next: Partial<Ui> = s.quoteBasketId === q.basket_id ? {} : { quoteBasketId: q.basket_id };
  if (s.basketId === null && q.basket_id) Object.assign(next, focusBasket({ ...s, ...next }, q.basket_id));
  return next;
}

/** show_products with a line_id: the option cards replace that line of the basket in focus. */
export function optionsFor(s: Ui, offerSetId: string, lineId: unknown): Partial<Ui> {
  const ok = typeof lineId === "number" && Number.isInteger(lineId) && lineId >= 1 && lineId <= 10_000;
  return { offerSetId, replaceLine: ok && s.basketId ? { basketId: s.basketId, lineId } : null };
}

/** A toast, optionally with one action button (such as Undo). */
export function showToast(text: string, action?: { label: string; run: () => void }): Partial<Ui> {
  return { toast: text, toastAction: action ? { text, ...action } : null };
}

/** The toast's action, only while the toast still shows the text it came with. */
export const toastActionOf = (s: Pick<Ui, "toast" | "toastAction">): ToastAction | null =>
  s.toastAction && s.toast !== null && s.toastAction.text === s.toast ? s.toastAction : null;

/** Simple event channel for "the call ended": settles pending confirmations. */
const disconnectListeners = new Set<() => void>();
export const onDisconnectEvent = (l: () => void) => {
  disconnectListeners.add(l);
  return () => {
    disconnectListeners.delete(l);
  };
};
export const emitDisconnect = () => disconnectListeners.forEach((l) => l());
