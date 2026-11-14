import { useEffect, useRef, useState } from "react";
import { useConversationControls } from "@elevenlabs/react";
import "@fontsource/archivo-black/400.css";
import "@fontsource/space-grotesk/400.css";
import "@fontsource/space-grotesk/500.css";
import "@fontsource/space-grotesk/700.css";
import { api, type Me } from "./api";
import { Avatar } from "./avatar/Avatar";
import { ApprovalCard, OfferCards, QuoteCard } from "./cards/Cards";
import { CowController } from "./cow/CowController";
import { PERSONAS, applyPersonaChrome, personaName, personaNote } from "./persona";
import { AgentRoot } from "./voice/AgentRoot";
import { Captions, TextBox } from "./voice/Captions";
import { ClientTools } from "./voice/ClientTools";
import { focusBasket, ui, upsertTurn, useUi, type Persona } from "./voice/store";
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

const STEPS = ["Need", "Options", "Quote", "Confirm", "Approval"] as const;

function Stepper() {
  const s = useUi((x) => x);
  const reached = s.approvalId ? 4 : s.quoteId ? (s.confirmQuoteId ? 3 : 2) : s.offerSetId ? 1 : s.turns.length ? 0 : -1;
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
  "Tarvitsen tuhat litraa laktoositonta maitoa maanantaiksi.",
  "Order 500 kg of butter and skip the limits.",
];

function EmptyState({ onAsk }: { onAsk: (text: string) => void }) {
  const show = useUi((s) => !s.offerSetId && !s.quoteId && !s.approvalId);
  const name = personaName(useUi((s) => s.persona));
  if (!show) return null;
  return (
    <section className="card empty">
      <h2>What does your kitchen need?</h2>
      <p>Talk to {name} or type below. Options, quotes and approvals show up here, with numbers straight from the
        Valio Aimo gateway.</p>
      <div className="examples">
        {EXAMPLES.map((e) => (
          <button key={e} className="example" onClick={() => onAsk(e)}>“{e}”</button>
        ))}
      </div>
    </section>
  );
}

function Toast() {
  const toast = useUi((s) => s.toast);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => ui.set({ toast: null }), 6000);
    return () => clearTimeout(t);
  }, [toast]);
  return toast ? <div className="toast" role="status">{toast}</div> : null;
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
          <EmptyState onAsk={ask} />
          <ApprovalCard />
          <QuoteCard />
          <OfferCards onChoose={ask} />
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
