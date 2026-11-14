import { useEffect, useState } from "react";
import { api, helsinki, type Me } from "./api";
import { Avatar } from "./avatar/Avatar";
import { ApprovalCard, OfferCards, QuoteCard } from "./cards/Cards";
import { CowController } from "./cow/CowController";
import { AgentRoot } from "./voice/AgentRoot";
import { Captions, TextBox } from "./voice/Captions";
import { ClientTools } from "./voice/ClientTools";
import { ui, useUi, type Persona } from "./voice/store";
import { useSession } from "./voice/useSession";

function Login({ onDone }: { onDone: (me: Me) => void }) {
  const [err, setErr] = useState<string | null>(null);
  const go = (id: "chef" | "head_chef") => api.login(id).then(onDone, (e: unknown) => setErr(String(e)));
  return (
    <main className="login">
      <h1>Valio Aimo ordering assistant</h1>
      <p>Demo sign-in. Real buyers sign in with their company account.</p>
      <button className="primary" onClick={() => void go("chef")}>Sign in as Chef Aada (500 € order cap)</button>
      {err && <p className="error">Could not sign in: {err}. Is the gateway running on port 8000?</p>}
    </main>
  );
}

function PersonaSwitch() {
  const persona = useUi((s) => s.persona);
  const set = (p: Persona) => ui.set({ persona: p });
  return (
    <div className="persona" role="radiogroup" aria-label="Persona">
      {(["aino", "cow"] as const).map((p) => (
        <button key={p} role="radio" aria-checked={persona === p} className={persona === p ? "on" : ""} onClick={() => set(p)}>
          {p === "aino" ? "Aino" : "Mansikki 🐄"}
        </button>
      ))}
    </div>
  );
}

function CallControls() {
  const { start, stop } = useSession();
  const phase = useUi((s) => s.phase);
  const transport = useUi((s) => s.transport);
  const busy = phase === "connecting";
  return (
    <div className="call">
      {phase === "live" ? (
        <button className="danger" onClick={stop}>End {transport === "text" ? "chat" : "call"}</button>
      ) : (
        <button className="primary" disabled={busy} onClick={() => void start("voice")}>
          {busy ? "Connecting…" : "Talk to Aino"}
        </button>
      )}
      {phase === "live" && transport && <span className="muted">via {transport}</span>}
    </div>
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

function Workspace({ me }: { me: Me }) {
  const { start } = useSession();
  const persona = useUi((s) => s.persona);
  return (
    <div className={`app persona-${persona}`}>
      <header className="top">
        <strong>Valio Aimo · AI ordering</strong>
        <span className="badge" title="Demo clock: all cut-offs are computed at this time">As of {helsinki(me.as_of)}</span>
        <span className="who">{me.display_name}</span>
        <PersonaSwitch />
      </header>
      <p className="notice" role="note">
        You are talking to an AI assistant. Calls are recorded and processed by our service providers.
        {persona === "cow" && " Mansikki's voice is muted; the captions show what she says."}{" "}
        <a href="#privacy">Privacy</a>
      </p>
      <main className="stage">
        <div className="left">
          <Avatar />
          <CallControls />
          <Captions />
          <TextBox onStartText={() => void start("text")} />
        </div>
        <div className="right">
          <ApprovalCard />
          <QuoteCard />
          <OfferCards />
        </div>
      </main>
      <footer id="privacy" className="muted">
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
      <Workspace me={me} />
    </AgentRoot>
  );
}
