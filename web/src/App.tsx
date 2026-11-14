import { useCallback, useEffect, useRef, useState } from "react";
import { useConversationControls } from "@elevenlabs/react";
import "@fontsource/archivo-black/400.css";
import "@fontsource/space-grotesk/400.css";
import "@fontsource/space-grotesk/500.css";
import "@fontsource/space-grotesk/700.css";
import { api, type Me } from "./api";
import { Avatar } from "./avatar/Avatar";
import { BasketCard } from "./cards/BasketCard";
import { ApprovalCard, OfferCards, QuoteCard } from "./cards/Cards";
import { CowController } from "./cow/CowController";
import { DishForm } from "./imports/DishForm";
import { buyerLanguage } from "./imports/dish";
import { PhotoImport } from "./imports/PhotoImport";
import { SheetImport } from "./imports/SheetImport";
import { useIntake } from "./imports/useIntake";
import { PERSONAS, applyPersonaChrome, personaName, personaNote } from "./persona";
import { STEPS, stepReached } from "./steps";
import { AgentRoot } from "./voice/AgentRoot";
import { Captions, TextBox } from "./voice/Captions";
import { ClientTools } from "./voice/ClientTools";
import { focusBasket, toastActionOf, ui, upsertTurn, useUi, type Persona } from "./voice/store";
import { useSession } from "./voice/useSession";

function Login({ onDone }: { onDone: (me: Me) => void }) {
  const [err, setErr] = useState<string | null>(null);
  const go = (id: "chef" | "head_chef") => api.login(id).then(onDone, (e: unknown) => setErr(String(e)));
  return (
    <main className="login">
      <p className="kicker">Valio Aimo · Junction 2026</p>
      <h1>Order for your kitchen by talking.</h1>
      <p>Aino finds products, checks price and stock, and makes a fixed-price quote. Your limits are enforced by the
        gateway, never by the AI.</p>
      <button className="primary big" onClick={() => void go("chef")}>Sign in as Chef Aada (demo, 500 € cap)</button>
      {err && <p className="error">Could not sign in: {err}. Is the gateway running?</p>}
    </main>
  );
}

function PersonaSwitch() {
  const persona = useUi((s) => s.persona);
  return (
    <div className="persona" role="radiogroup" aria-label="Persona">
      {(["aino", "cow"] as const).map((p) => (
        <button key={p} role="radio" aria-checked={persona === p} className={persona === p ? "on" : ""}
                onClick={() => ui.set({ persona: p })}>
          {PERSONAS[p].short}
        </button>
      ))}
    </div>
  );
}

/** Mid-call persona switch: the same session continues; the agent gets a silent note with its new name. */
function PersonaSync() {
  const persona = useUi((s) => s.persona);
  useEffect(() => applyPersonaChrome(persona), [persona]);
  const live = useUi((s) => s.phase === "live");
  const { sendContextualUpdate } = useConversationControls();
  const last = useRef<Persona>(persona);
  useEffect(() => {
    if (last.current === persona) return;
    last.current = persona;
    if (!live) return;
    try {
      sendContextualUpdate(personaNote(persona));
    } catch {
      /* call ended */
    }
  }, [persona, live, sendContextualUpdate]);
  return null;
}

/** Sends text typed before the chat connected, once it is live. */
function QueuedSender() {
  const live = useUi((s) => s.phase === "live");
  const queued = useUi((s) => s.queuedText);
  const { sendUserMessage } = useConversationControls();
  useEffect(() => {
    if (!live || !queued) return;
    const t = setTimeout(() => {
      try {
        sendUserMessage(queued);
        const id = `typed-${Date.now()}`;
        ui.set((s) => ({ queuedText: null, turns: upsertTurn(s.turns, id, "user", () => ({ id, role: "user", text: queued, final: true })) }));
      } catch {
        /* not ready yet: the next render retries */
      }
    }, 600); // let the first message start
    return () => clearTimeout(t);
  }, [live, queued, sendUserMessage]);
  return null;
}

function CallControls() {
  const { start, stop } = useSession();
  const phase = useUi((s) => s.phase);
  const transport = useUi((s) => s.transport);
  const name = personaName(useUi((s) => s.persona));
  return (
    <div className="call">
      {phase === "live" ? (
        <button className="danger" onClick={stop}>End {transport === "text" ? "chat" : "call"}</button>
      ) : (
        <button className="primary big" disabled={phase === "connecting"} onClick={() => void start("voice")}>
          {phase === "connecting" ? "Connecting…" : `🎙 Talk to ${name}`}
        </button>
      )}
      {phase === "live" && transport && <span className="chip">{transport === "text" ? "text chat" : `voice · ${transport}`}</span>}
    </div>
  );
}

function Stepper() {
  const reached = useUi(stepReached);
  return (
    <ol className="stepper" aria-label="Order progress">
      {STEPS.map((label, i) => (
        <li key={label} className={i < reached ? "done" : i === reached ? "now" : ""} aria-current={i === reached ? "step" : undefined}>
          <span>{i + 1}</span>{label}
        </li>
      ))}
    </ol>
  );
}

const EXAMPLES = [
  "I need 1,000 litres of lactose-free milk for Monday.",
  "Tuhat litraa laktoositonta maitoa ja 20 kg voita maanantaiksi.",
  "Order 500 kg of butter and skip the limits.",
];

/**
 * Before there is a basket: four ways in. Talk or type to the agent, drop an Excel or CSV list, send a photo of a
 * list, or name a dish. Each intake starts a basket; the page then shows it instead of this.
 */
function EmptyState({ onAsk, asOf }: { onAsk: (text: string) => void; asOf: string }) {
  const show = useUi((s) => !s.offerSetId && !s.basketId && !s.quoteId && !s.approvalId);
  const name = personaName(useUi((s) => s.persona));
  const intake = useIntake();
  if (!show) return null;
  return (
    <>
      <section className="card empty" aria-labelledby="empty-title">
        <h2 id="empty-title">What does your kitchen need?</h2>
        <p>Talk to {name} or type below, one product or many. Your basket, options, quotes and approvals show up here,
          with numbers straight from the Valio Aimo gateway.</p>
        <div className="examples">
          {EXAMPLES.map((e) => (
            <button key={e} className="example" onClick={() => onAsk(e)}>“{e}”</button>
          ))}
        </div>
        <h3 className="ways-title">Or start from a list</h3>
        <SheetImport basketId={null} onImported={intake.sheet} />
      </section>
      <div className="ways">
        <PhotoImport basketId={null} onImported={intake.photo} />
        <DishForm basketId={null} asOf={asOf} language={buyerLanguage()} onPlanned={intake.dish} />
      </div>
    </>
  );
}

/**
 * Announced (a live region that is always there), and it can carry one action such as Undo. It stays while the
 * pointer or the focus is on it; when the control that was clicked is gone, focus moves to the action.
 */
function Toast() {
  const toast = useUi((s) => s.toast);
  const action = useUi(toastActionOf);
  const box = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const [hover, setHover] = useState(false);
  const [focused, setFocused] = useState(false);
  const dismiss = useCallback(() => {
    const hadFocus = !!box.current?.contains(document.activeElement);
    ui.set({ toast: null, toastAction: null });
    if (hadFocus) (document.getElementById("basket-title") ?? document.getElementById("say"))?.focus();
  }, []);
  useEffect(() => {
    if (!toast || hover || focused) return;
    const t = setTimeout(dismiss, action ? 10_000 : 6000);
    return () => clearTimeout(t);
  }, [toast, action, hover, focused, dismiss]);
  useEffect(() => {
    const a = document.activeElement;
    if (action && (!a || a === document.body)) button.current?.focus();
  }, [action]);
  return (
    <div className="toast-region" role="status" aria-live="polite">
      {toast && (
        <div className="toast" ref={box} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
             onFocus={() => setFocused(true)}
             onBlur={(e) => {
               if (!box.current?.contains(e.relatedTarget as Node)) setFocused(false);
             }}
             onKeyDown={(e) => {
               if (e.key === "Escape") dismiss();
             }}>
          <span>{toast}</span>
          {action && (
            <button type="button" ref={button} className="small" onClick={() => {
              setFocused(false);
              ui.set({ toast: null, toastAction: null });
              action.run();
            }}>
              {action.label}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/** After sign-in, or a reload, the buyer's newest open basket comes back into focus (B-03). */
function useRestoreBasket(buyerId: string) {
  useEffect(() => {
    let alive = true;
    api.currentBasket().then(
      (r) => {
        if (alive && r) ui.set((s) => (s.basketId ? {} : focusBasket(s, r.basket_id, r.basket)));
      },
      () => {
        /* no basket to restore: the screen starts empty */
      },
    );
    return () => {
      alive = false;
    };
  }, [buyerId]);
}

function Workspace({ me }: { me: Me }) {
  useRestoreBasket(me.buyer_id);
  const { start } = useSession();
  const persona = useUi((s) => s.persona);
  const live = useUi((s) => s.phase === "live");
  const { sendUserMessage } = useConversationControls();
  const ask = (text: string) => {
    if (live) {
      try {
        sendUserMessage(text);
        const id = `typed-${Date.now()}`;
        ui.set((s) => ({ turns: upsertTurn(s.turns, id, "user", () => ({ id, role: "user", text, final: true })) }));
      } catch {
        ui.set({ toast: "Not connected yet." });
      }
      return;
    }
    ui.set({ queuedText: text });
    void start("text");
  };
  return (
    <div className={`app persona-${persona}`}>
      <header className="top">
        <span className="logo" aria-hidden="true">V</span>
        <strong className="title">Valio Aimo <span>AI ordering</span></strong>
        <span className="who">{me.display_name}</span>
        <PersonaSwitch />
      </header>
      <p className="notice" role="note">
        <strong>You are talking to an AI.</strong> Calls are recorded and processed by our service providers.
        {persona === "cow" && " Mansikki's voice is muted: she moos, and the captions show what she says."}{" "}
        <a href="#privacy">Privacy</a>
      </p>
      <main className="stage">
        <div className="left">
          <Avatar />
          <CallControls />
          <Captions />
          <TextBox onAsk={ask} />
        </div>
        <div className="right">
          <Stepper />
          <EmptyState onAsk={ask} asOf={me.as_of} />
          <ApprovalCard />
          <QuoteCard onAsk={ask} />
          <OfferCards />
          <BasketCard asOf={me.as_of} />
        </div>
      </main>
      <footer id="privacy">
        Privacy: conversations are kept for at most 30 days and are not used to identify your voice. Prices, limits and
        approvals are decided by the Valio Aimo gateway, never by the AI. Demo build with contract stubs.
      </footer>
      <Toast />
    </div>
  );
}

export function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  useEffect(() => {
    api.me().then(setMe, () => setMe(null));
  }, []);
  if (me === undefined) return null;
  if (me === null) return <Login onDone={setMe} />;
  return (
    <AgentRoot>
      <ClientTools />
      <CowController />
      <PersonaSync />
      <QueuedSender />
      <Workspace me={me} />
    </AgentRoot>
  );
}
