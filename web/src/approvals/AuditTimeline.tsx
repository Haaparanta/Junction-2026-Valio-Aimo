import { useEffect, useRef } from "react";
import { api } from "../api";
import { useFetch } from "../cards/useFetch";
import { timelineRows } from "./timeline";

/**
 * "What happened" for one order (PLAN M10.4): the audit entries, oldest first, folded by default. Hidden while
 * GET /v1/orders/{id}/audit answers 404 (no audit trail yet). `version` changes when the order's status does,
 * which loads the entries again.
 */
export function AuditTimeline({ orderId, version }: { orderId: string; version: string }) {
  const { data, error, reload } = useFetch(orderId, api.orderAudit);
  const seen = useRef(version);
  useEffect(() => {
    if (seen.current === version) return;
    seen.current = version;
    reload();
  }, [version, reload]);
  if (error) return <p className="muted">The audit trail could not be loaded: {error}</p>;
  if (!data || data.events.length === 0) return null;
  const rows = timelineRows(data.events);
  return (
    <details className="timeline">
      <summary>What happened ({rows.length})</summary>
      <ol>
        {rows.map((r) => (
          <li key={r.key}>
            <p className="tl-head">
              <strong>{r.action}</strong>
              {r.decision && <span className="chip">{r.decision.replace(/_/g, " ")}</span>}
            </p>
            <p className="tl-meta">
              <time dateTime={r.at}>{r.when}</time> · {r.actor} · {r.channel}
            </p>
            {r.text && <p>{r.text}</p>}
            <p className="tl-hash muted" title={`Entry ${r.seq}; links to ${r.prevHash || "the start"}`}>
              #{r.seq} · hash <code>{r.hash}</code>
            </p>
          </li>
        ))}
      </ol>
    </details>
  );
}
