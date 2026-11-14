import type { ReactNode } from "react";
import { ConversationProvider } from "@elevenlabs/react";
import { GATEWAY_TOOLS, outcomeFromTool } from "../cow/mood";
import { emitDisconnect, ui, upsertTurn } from "./store";
import { stripTags } from "./text";

type IncomingEvent = { type?: string; queue_status?: { status?: string } } | null | undefined;

function disconnectMessage(d: { reason: string; closeCode?: number; message?: string }): string | null {
  if (d.closeCode === 4300) return "All lines are busy right now. Please try again in a minute.";
  if (d.reason === "agent") return "Aino ended the call.";
  if (d.reason === "error") return `The call dropped: ${d.message ?? "network error"}`;
  return null;
}

/** Wires the SDK's callbacks into the external store. "Live" comes from connect and disconnect only. */
export function AgentRoot({ children }: { children: ReactNode }) {
  return (
    <ConversationProvider
      onConnect={({ conversationId }) =>
        ui.set({ phase: "live", conversationId, lastError: null, queue: null, pendingTools: {} })
      }
      onDisconnect={(d) => {
        const msg = disconnectMessage(d as { reason: string; closeCode?: number; message?: string });
        ui.set({ phase: "idle", mode: "listening", userSpeaking: false, pendingTools: {}, queue: null, toast: msg,
                 lastError: d.reason === "error" ? msg : null });
        emitDisconnect();
      }}
      onError={(message) => {
        // Often non-fatal (a tool error); before onConnect it means the start failed.
        ui.set((s) => (s.phase === "connecting" ? { phase: "error", lastError: message } : { toast: message }));
      }}
      onModeChange={({ mode }) => ui.set({ mode })}
      onVadScore={({ vadScore }) => {
        const speaking = vadScore > 0.5;
        if (speaking !== ui.get().userSpeaking) ui.set({ userSpeaking: speaking });
      }}
      onMessage={(m) => {
        const role = m.source === "user" ? "user" : "agent";
        const id = role === "agent" && m.response_id ? m.response_id : `${role}-${m.event_id}`;
        const text = stripTags(m.message);
        if (!text) return;
        ui.set((s) => ({ turns: upsertTurn(s.turns, id, role, () => ({ id, role, text, final: true })) }));
      }}
      onAgentChatResponsePart={(p) => {
        if (p.type !== "delta") return;
        const id = p.response_id ?? `draft-${p.event_id}`;
        ui.set((s) => ({ turns: upsertTurn(s.turns, id, "agent", (t) => (t.final ? t : { ...t, text: t.text + p.text })) }));
      }}
      onAgentResponseCorrection={(c) => {
        const id = c.response_id;
        if (!id) return;
        const text = stripTags(c.corrected_agent_response);
        ui.set((s) => ({ turns: upsertTurn(s.turns, id, "agent", (t) => ({ ...t, text, final: true })) }));
      }}
      onAgentToolRequest={(t) => {
        if (!GATEWAY_TOOLS.has(t.tool_name)) return; // "thinking" only while the gateway works
        ui.set((s) => ({ pendingTools: { ...s.pendingTools, [t.tool_call_id]: { tool: t.tool_name, since: Date.now() } } }));
      }}
      onAgentToolResponse={(t) => {
        // Fires for both tool events; the full payload carries the gateway's status.
        const rest = { ...ui.get().pendingTools };
        delete rest[t.tool_call_id];
        const outcome = "full_tool_result" in t && GATEWAY_TOOLS.has(t.tool_name) ? outcomeFromTool(t) : null;
        ui.set(outcome ? { pendingTools: rest, lastOutcome: { tool: t.tool_name, ...outcome, at: Date.now() } }
                       : { pendingTools: rest });
      }}
      onIncomingEvent={(e: IncomingEvent) => {
        if (e?.type === "queue_status") {
          const st = e.queue_status?.status;
          if (st === "waiting" || st === "admitted" || st === "timed_out") ui.set({ queue: st });
        }
      }}
    >
      {children}
    </ConversationProvider>
  );
}
