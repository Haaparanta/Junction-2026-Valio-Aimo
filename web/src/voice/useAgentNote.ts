import { useCallback } from "react";
import { useConversationControls } from "@elevenlabs/react";
import { ui } from "./store";

/**
 * Sends a silent contextual update to the agent, only while a call is live. Notes come from voice/notes.ts, which
 * builds them from gateway fields only.
 */
export function useAgentNote(): (note: string | null) => void {
  const { sendContextualUpdate } = useConversationControls();
  return useCallback(
    (note: string | null) => {
      if (!note || ui.get().phase !== "live") return;
      try {
        sendContextualUpdate(note);
      } catch {
        /* the call just ended */
      }
    },
    [sendContextualUpdate],
  );
}
