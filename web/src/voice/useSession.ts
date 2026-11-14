/**
 * Session start with the fallback ladder (PLAN M15.5): microphone check, WebRTC, WebRTC over TURN relay,
 * WebSocket, then text only. Fresh credentials from the gateway for every attempt.
 */
import { useCallback } from "react";
import { useConversationControls, type Conversation } from "@elevenlabs/react";
import { api, HttpError, type Session } from "../api";
import { mooPlayer } from "../cow/MooPlayer";
import { personaName } from "../persona";
import { ui, type Transport } from "./store";

const CONNECT_TIMEOUT_MS = 10_000;

export type MicCheck = "ok" | "denied" | "missing" | "busy" | "insecure";

export async function checkMicrophone(): Promise<MicCheck> {
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) return "insecure";
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach((t) => t.stop());
    return "ok";
  } catch (e) {
    const name = e instanceof DOMException ? e.name : "";
    if (name === "NotAllowedError" || name === "SecurityError") return "denied";
    if (name === "NotFoundError") return "missing";
    return "busy"; // NotReadableError: another app holds the microphone
  }
}

const MIC_MESSAGES: Record<Exclude<MicCheck, "ok">, string> = {
  denied: "Microphone access is blocked. Allow it in the address bar, or keep typing below.",
  missing: "No microphone found. You can type to Aino below.",
  busy: "Another app is using the microphone. You can type to Aino below.",
  insecure: "The microphone needs HTTPS or localhost. You can type to Aino below.",
};

/** Resolves true on onConnect, false on a failed start, a drop or the timeout. */
function waitForConnect(): Promise<boolean> {
  return new Promise((resolve) => {
    const t = setTimeout(() => done(false), CONNECT_TIMEOUT_MS);
    const unsub = ui.subscribe(() => {
      const p = ui.get().phase;
      if (p === "live") done(true);
      else if (p === "error" || p === "idle") done(false);
    });
    function done(ok: boolean) {
      clearTimeout(t);
      unsub();
      resolve(ok);
    }
  });
}

export function useSession() {
  const { startSession, endSession } = useConversationControls();

  const startOne = useCallback(
    async (transport: Transport): Promise<boolean> => {
      const s: Session = await api.agentSession(transport === "webrtc" || transport === "relay" ? "webrtc" : "websocket");
      const common = {
        userId: s.user_id, // pseudonym, analytics only
        // secret__ reaches tool headers only, never the LLM. persona_name is only ever "Aino" or "Mansikki".
        dynamicVariables: { secret__session_token: s.session_token, persona_name: personaName(ui.get().persona) },
        onConversationCreated: (c: Conversation) => {
          // Cow mode: same agent, voice muted from the first word (PLAN M17.2).
          if (ui.get().persona === "cow" && transport !== "text") {
            try {
              c.setVolume({ volume: 0 });
            } catch {
              /* text session */
            }
          }
        },
      };
      ui.set({ phase: "connecting", transport, lastError: null });
      if (transport === "text") {
        if (!s.signed_url) throw new Error("no signed URL");
        startSession({ ...common, signedUrl: s.signed_url, connectionType: "websocket", textOnly: true,
                       overrides: { conversation: { textOnly: true } } });
      } else if (transport === "websocket") {
        if (!s.signed_url) throw new Error("no signed URL");
        startSession({ ...common, signedUrl: s.signed_url, connectionType: "websocket" });
      } else {
        if (!s.conversation_token) throw new Error("no conversation token");
        startSession({ ...common, conversationToken: s.conversation_token, connectionType: "webrtc",
                       ...(transport === "relay" ? { webRtc: { iceTransportPolicy: "relay" as const } } : {}) });
      }
      return waitForConnect();
    },
    [startSession],
  );

  const start = useCallback(
    async (kind: "voice" | "text") => {
      mooPlayer.unlock(); // inside the click: unlock Web Audio for the moos
      let ladder: Transport[] = ["text"];
      if (kind === "voice") {
        const mic = await checkMicrophone();
        if (mic === "ok") ladder = ["webrtc", "relay", "websocket", "text"];
        else ui.set({ toast: MIC_MESSAGES[mic] });
      }
      for (const transport of ladder) {
        try {
          if (await startOne(transport)) return;
        } catch (e) {
          if (e instanceof HttpError && e.status === 401) {
            ui.set({ phase: "idle", toast: "Please sign in again." });
            return;
          }
          ui.set({ lastError: e instanceof Error ? e.message : String(e) });
        }
        if (ui.get().queue === "timed_out") {
          ui.set({ phase: "idle", toast: "All lines are busy right now. Please try again in a minute." });
          return;
        }
        try {
          endSession();
        } catch {
          /* nothing to end */
        }
        await new Promise((r) => setTimeout(r, 300));
      }
      ui.set({ phase: "error", toast: "Could not connect. Check the network, or try again." });
    },
    [startOne, endSession],
  );

  const stop = useCallback(() => {
    try {
      endSession();
    } catch {
      /* already ended */
    }
  }, [endSession]);

  return { start, stop };
}
