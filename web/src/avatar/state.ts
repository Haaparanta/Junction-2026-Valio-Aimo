/** Avatar state and expression, derived from SDK events and gateway status (never from LLM text). */
import type { Ui } from "../voice/store";

export type AvatarState = "idle" | "connecting" | "queued" | "listening" | "userSpeaking" | "thinking" | "speaking" | "error";
export type Expression = "neutral" | "concerned" | "happy";

export const THINKING_WATCHDOG_MS = 15_000;

export function avatarState(s: Pick<Ui, "phase" | "queue" | "mode" | "userSpeaking" | "pendingTools">, now: number): AvatarState {
  if (s.phase === "error") return "error";
  if (s.phase === "idle") return "idle";
  if (s.phase === "connecting") return "connecting";
  if (s.queue === "waiting") return "queued";
  if (s.mode === "speaking") return "speaking";
  const thinking = Object.values(s.pendingTools).some((p) => now - p.since < THINKING_WATCHDOG_MS);
  if (thinking) return "thinking";
  if (s.userSpeaking) return "userSpeaking";
  return "listening";
}

export function expression(outcome: Ui["lastOutcome"], now: number): Expression {
  if (!outcome || now - outcome.at > 60_000) return "neutral";
  if (outcome.status === "completed") return "happy";
  if (outcome.status === "requires_escalation" || outcome.status === "canceled" || outcome.reasonCode) return "concerned";
  return "neutral";
}
