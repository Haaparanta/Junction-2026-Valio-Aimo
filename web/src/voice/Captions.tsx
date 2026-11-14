import { useState } from "react";
import { useConversationControls } from "@elevenlabs/react";
import { ui, upsertTurn, useUi } from "./store";
import { stripTags } from "./text";

export function Captions() {
  const turns = useUi((s) => s.turns);
  const persona = useUi((s) => s.persona);
  return (
    <section className="captions" aria-label="Captions" aria-live="polite">
      {turns.slice(-4).map((t) => (
        <p key={t.id} className={`turn ${t.role}${t.final ? "" : " partial"}`}>
          <span className="who">{t.role === "user" ? "You" : persona === "cow" ? "Mansikki" : "Aino"}</span>
          {stripTags(t.text)}
        </p>
      ))}
    </section>
  );
}

/** Always visible (PLAN M15.3): typing works in voice calls and in the text fallback. */
export function TextBox({ onStartText }: { onStartText: () => void }) {
  const [text, setText] = useState("");
  const live = useUi((s) => s.phase === "live");
  const { sendUserMessage } = useConversationControls();
  const send = () => {
    const t = text.trim();
    if (!t) return;
    if (!live) {
      onStartText();
      return;
    }
    try {
      sendUserMessage(t);
      const id = `typed-${Date.now()}`;
      ui.set((s) => ({ turns: upsertTurn(s.turns, id, "user", () => ({ id, role: "user", text: t, final: true })) }));
      setText("");
    } catch {
      ui.set({ toast: "Not connected yet." });
    }
  };
  return (
    <form className="textbox" onSubmit={(e) => { e.preventDefault(); send(); }}>
      <label htmlFor="say" className="sr-only">Message to Aino</label>
      <input id="say" value={text} onChange={(e) => setText(e.target.value)} autoComplete="off"
             placeholder={live ? "Type a message…" : "Type to start a text chat…"} />
      <button type="submit">{live ? "Send" : "Start text chat"}</button>
    </form>
  );
}
