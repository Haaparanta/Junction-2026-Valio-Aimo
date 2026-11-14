/** A tiny external store: SDK callbacks write here, components subscribe with selectors (no per-frame renders). */
import { useSyncExternalStore } from "react";

export type Persona = "aino" | "cow";
export type Transport = "webrtc" | "relay" | "websocket" | "text";
export type Turn = { id: string; role: "user" | "agent"; text: string; final: boolean };
export type GatewayOutcome = { tool: string; status: string; reasonCode: string | null; at: number };

export type Ui = {
  phase: "idle" | "connecting" | "live" | "error";
  transport: Transport | null;
  conversationId: string | null;
  mode: "speaking" | "listening";
  userSpeaking: boolean;
  pendingTools: Record<string, { tool: string; since: number }>;
  turns: Turn[];
  toast: string | null;
  lastError: string | null;
  lastOutcome: GatewayOutcome | null;
  queue: "waiting" | "admitted" | "timed_out" | null;
  persona: Persona;
  offerSetId: string | null;
  quoteId: string | null;
  approvalId: string | null;
  confirmQuoteId: string | null;
  queuedText: string | null; // typed before a chat connected: sent on connect
};

export const initialUi: Ui = {
  phase: "idle", transport: null, conversationId: null, mode: "listening", userSpeaking: false, pendingTools: {},
  turns: [], toast: null, lastError: null, lastOutcome: null, queue: null, persona: "aino", offerSetId: null,
  quoteId: null, approvalId: null, confirmQuoteId: null, queuedText: null,
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

/** Simple event channel for "the call ended": settles pending confirmations. */
const disconnectListeners = new Set<() => void>();
export const onDisconnectEvent = (l: () => void) => {
  disconnectListeners.add(l);
  return () => {
    disconnectListeners.delete(l);
  };
};
export const emitDisconnect = () => disconnectListeners.forEach((l) => l());
