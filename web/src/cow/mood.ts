/** Moo moods come from the gateway's status in tool results, not from the LLM (PLAN M17.3). */
export type Mood = "greet" | "happy" | "question" | "alarmed" | "celebrate";

export const GATEWAY_TOOLS = new Set([
  "search_products", "get_product", "plan_quantity", "get_offers", "find_substitutes", "create_quote", "place_order",
  "get_order", "get_approval", "cancel_order",
]);

export type ToolEvent = { is_error: boolean; is_blocked?: boolean; truncated?: boolean; full_tool_result?: string };

export function moodFromTool(e: ToolEvent): Mood | null {
  if (e.is_error || e.is_blocked) return "alarmed";
  if (!e.full_tool_result || e.truncated) return null; // cut above 64 KB: do not parse
  try {
    const r = JSON.parse(e.full_tool_result) as { status?: string; reason_code?: string | null };
    if (r.status === "requires_escalation" || r.status === "canceled" || r.reason_code) return "alarmed";
    if (r.status === "completed") return "celebrate";
  } catch {
    /* not JSON */
  }
  return null;
}

/** Parse status and reason_code out of a full tool payload for the avatar's expression. */
export function outcomeFromTool(e: ToolEvent): { status: string; reasonCode: string | null } | null {
  if (!e.full_tool_result || e.truncated) return e.is_error ? { status: "error", reasonCode: "tool_error" } : null;
  try {
    const r = JSON.parse(e.full_tool_result) as { status?: unknown; reason_code?: unknown };
    if (typeof r.status !== "string") return null;
    return { status: r.status, reasonCode: typeof r.reason_code === "string" ? r.reason_code : null };
  } catch {
    return null;
  }
}
