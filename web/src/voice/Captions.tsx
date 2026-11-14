import { useEffect, useRef, useState } from "react";
import { personaName } from "../persona";
import { useUi } from "./store";
import { stripTags } from "./text";

export function Captions() {
  const turns = useUi((s) => s.turns);
  const name = personaName(useUi((s) => s.persona));
  const thinking = useUi((s) => Object.keys(s.pendingTools).length > 0);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // Braces matter: newer Chrome returns a Promise from scrollIntoView, and an effect may only return a cleanup.
    void end.current?.scrollIntoView({ block: "nearest" });
  }, [turns, thinking]);
  return (
    <section className="captions" aria-label="Captions" aria-live="polite">
      {turns.length === 0 && <p className="muted">Captions appear here.</p>}
      {turns.slice(-6).map((t) => (
        <p key={t.id} className={`turn ${t.role}${t.final ? "" : " partial"}`}>
          <span className="who">{t.role === "user" ? "You" : name}</span>
          {stripTags(t.text)}
        </p>
      ))}
      {thinking && <p className="turn agent typing" aria-label={`${name} is checking with the gateway`}><span className="who">{name}</span><i /><i /><i /></p>}
      <div ref={end} />
    </section>
  );
}

/** Always visible (PLAN M15.3): typing works in voice calls, and starts a text chat when no call is running. */
export function TextBox({ onAsk }: { onAsk: (text: string) => void }) {
  const [text, setText] = useState("");
  const live = useUi((s) => s.phase === "live");
  const name = personaName(useUi((s) => s.persona));
  const send = () => {
    const t = text.trim();
    if (!t) return;
    onAsk(t);
    setText("");
  };
  return (
    <form className="textbox" onSubmit={(e) => { e.preventDefault(); send(); }}>
      <label htmlFor="say" className="sr-only">Message to {name}</label>
      <input id="say" value={text} onChange={(e) => setText(e.target.value)} autoComplete="off"
             placeholder={live ? `Message ${name}…` : `Type to ${name} to start a text chat…`} />
      <button type="submit">{live ? "Send" : "Chat"}</button>
    </form>
  );
}
