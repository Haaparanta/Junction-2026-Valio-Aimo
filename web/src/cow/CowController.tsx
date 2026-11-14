/**
 * Mansikki: the same agent with its voice muted; moos chosen from gateway status, captions carry the words.
 * Mounted for the whole session (listeners are composed at startSession) and toggled by persona.
 */
import { useEffect, useRef } from "react";
import { useConversation } from "@elevenlabs/react";
import { useUi } from "../voice/store";
import { endsWithQuestion } from "../voice/text";
import { mooPlayer } from "./MooPlayer";
import { GATEWAY_TOOLS, moodFromTool, type Mood } from "./mood";

export function CowController() {
  const enabled = useUi((s) => s.persona === "cow");
  const on = useRef(enabled);
  on.current = enabled;
  const next = useRef<Mood>("greet");
  const draft = useRef("");
  const mooing = useRef(false);
  const wasMuted = useRef(false);

  // No `volume` prop: useConversation applies it with an unguarded setVolume (throws in text sessions).
  const { mode, status, isMuted, setMuted, setVolume } = useConversation({
    onAgentToolRequest: (t) => {
      if (on.current && GATEWAY_TOOLS.has(t.tool_name)) mooPlayer.startLoop();
    },
    onAgentToolResponse: (e) => {
      mooPlayer.stopLoop();
      if (!("full_tool_result" in e)) return;
      const m = moodFromTool(e);
      if (m) next.current = m;
    },
    onDisconnect: () => mooPlayer.stopLoop(), // a call that ends mid-tool sends no tool response
    onGuardrailTriggered: () => {
      next.current = "alarmed";
    },
    onAgentChatResponsePart: (p) => {
      draft.current = p.type === "start" ? "" : draft.current + (p.type === "delta" ? p.text : "");
      if (p.type === "stop" && next.current === "happy" && endsWithQuestion(draft.current)) next.current = "question";
    },
  });

  useEffect(() => {
    // Same agent: only its voice is silenced. Switching persona mid-call keeps the session.
    try {
      setVolume({ volume: enabled ? 0 : 1 });
    } catch {
      /* not connected yet, or a text-only session */
    }
  }, [enabled, status, setVolume]);

  useEffect(() => {
    const safeMute = (m: boolean) => {
      try {
        setMuted(m);
      } catch {
        /* call already closed */
      }
    };
    const stopMoo = () => {
      mooing.current = false;
      mooPlayer.stopOneShot();
      safeMute(wasMuted.current);
    };
    if (!enabled) {
      mooPlayer.stopLoop();
      if (mooing.current) stopMoo();
      return;
    }
    if (mode !== "speaking") {
      const t = setTimeout(() => mooing.current && stopMoo(), 400); // debounce speaker flicker
      return () => clearTimeout(t);
    }
    if (mooing.current) return;
    mooing.current = true;
    wasMuted.current = isMuted;
    safeMute(true); // keep moos out of the microphone (echo hardening, M17.5)
    void (async () => {
      for (let i = 0; i < 3 && mooing.current; i++) { // at most 3 moos per turn
        const m = next.current;
        next.current = "happy";
        await mooPlayer.play(m);
        await new Promise((r) => setTimeout(r, 350));
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, mode]);

  return null;
}
