import { useCallback, useEffect, useId, useRef, useState } from "react";
import { api, errorText, eur, HttpError, type ApprovalSummary, type Decision, type Me } from "../api";
import { useFetch } from "../cards/useFetch";
import {
  approvalIdFromPath, cleanComment, decisionMessage, isPending, MAX_COMMENT, type Outcome,
} from "./approvals";
import { AuditTimeline } from "./AuditTimeline";
import { Reason } from "./Reason";
import { when } from "./timeline";
import "./approvals.css";

const loadList = () => api.approvals();
const STATUS_TEXT: Record<string, string> = {
  requires_escalation: "Waiting", completed: "Approved", canceled: "Canceled",
};

function Result({ r }: { r: Outcome }) {
  return (
    <div className={`result tone-${r.tone}`}>
      <p><strong>{r.title}</strong></p>
      {r.detail && r.detail !== r.title && <p>{r.detail}</p>}
    </div>
  );
}

function Lines({ a }: { a: ApprovalSummary }) {
  return (
    <ul className="appr-lines" aria-label="Lines">
      {a.lines.map((l, i) => (
        <li key={`${i}-${l.name_fi}`}>
          <span className="qty">{l.qty} × {l.api_unit}</span>
          <span className="name">{l.name_fi}</span>
          <span className="num">{eur(l.line_net)}</span>
        </li>
      ))}
    </ul>
  );
}

/** One pending request: what, who, why, by when; Approve or Reject with an optional comment. */
function PendingItem({ a, result, highlight, onDecided }: {
  a: ApprovalSummary; result: Outcome | undefined; highlight: boolean;
  onDecided: (id: string, r: Outcome) => void;
}) {
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState<Decision | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    if (highlight) ref.current?.scrollIntoView({ block: "start" });
  }, [highlight]);
  const decide = async (d: Decision) => {
    if (busy) return;
    setBusy(d);
    setErr(null);
    try {
      const r = await api.decide(a.approval_id, d, cleanComment(comment));
      onDecided(a.approval_id, decisionMessage(d, r));
    } catch (e) {
      setErr(e instanceof HttpError && e.status === 403
        ? "Only an approver can decide. Sign in as the approver on this device."
        : `The decision did not go through: ${errorText(e)}`);
    } finally {
      setBusy(null);
    }
  };
  return (
    <article ref={ref} className={`card appr-item${highlight ? " focus" : ""}`} aria-labelledby={`${uid}-who`}>
      <header><span className="tier">Needs approval</span><span className="pid">{a.approval_id}</span></header>
      <h2 id={`${uid}-who`}>{a.buyer_name}</h2>
      <p className="big">{eur(a.total_gross)} <small>incl. VAT · {eur(a.total_net)} excl.</small></p>
      <p>Delivery {a.delivery_date} · <strong>decide by {when(a.decide_by)}</strong></p>
      <ul className="reasons" aria-label="Why it needs you">{a.reasons.map((r) => <li key={r}><Reason text={r} /></li>)}</ul>
      <details className="appr-lines-box">
        <summary>{a.lines.length} {a.lines.length === 1 ? "line" : "lines"} · order {a.order_id}</summary>
        <Lines a={a} />
      </details>
      <label className="comment" htmlFor={`${uid}-comment`}>Comment for the buyer (optional)</label>
      <textarea id={`${uid}-comment`} rows={2} maxLength={MAX_COMMENT} value={comment} disabled={busy !== null}
                onChange={(e) => setComment(e.target.value)} />
      <div className="decide" role="group" aria-label={`Decide on ${a.approval_id}`}>
        <button type="button" className="approve big" disabled={busy !== null} aria-busy={busy === "approve"}
                onClick={() => void decide("approve")}>
          {busy === "approve" ? "Approving…" : "Approve"}
        </button>
        <button type="button" className="danger big" disabled={busy !== null} aria-busy={busy === "reject"}
                onClick={() => void decide("reject")}>
          {busy === "reject" ? "Rejecting…" : "Reject"}
        </button>
      </div>
      {result && <Result r={result} />}
      {err && <p className="error" role="alert">{err}</p>}
    </article>
  );
}

function DecidedItem({ a, result }: { a: ApprovalSummary; result: Outcome | undefined }) {
  return (
    <li className={`card appr-done status-${a.status}`}>
      <p className="appr-done-head">
        <span className="chip">{STATUS_TEXT[a.status] ?? a.status}</span>
        <strong>{a.buyer_name}</strong> · {eur(a.total_gross)} · order {a.order_id}
      </p>
      {result && <Result r={result} />}
      <AuditTimeline orderId={a.order_id} version={a.status} />
    </li>
  );
}

/**
 * The approver's phone-first console (PLAN M9.3): pending requests of the approver's own org, polled every 2 s
 * (M9.2). A decision goes to POST /v1/approvals/{id}/decision under this approver session only (M9.5); the
 * gateway's answer is shown in plain language.
 */
export function ApproverConsole({ me, onSignOut }: { me: Me; onSignOut: () => void }) {
  const { data, error } = useFetch("approvals", loadList, 2000);
  const [results, setResults] = useState<Record<string, Outcome>>({});
  const [latest, setLatest] = useState<Outcome | null>(null);
  const focusId = approvalIdFromPath(window.location.pathname);
  const latestRef = useRef<HTMLDivElement>(null);
  const onDecided = useCallback((id: string, r: Outcome) => {
    setResults((m) => ({ ...m, [id]: r }));
    setLatest(r);
  }, []);
  useEffect(() => {
    if (latest) latestRef.current?.focus(); // the decided card may leave the list on the next poll
  }, [latest]);
  const all = data?.approvals ?? [];
  const pending = all.filter((a) => isPending(a.status));
  const decided = all.filter((a) => !isPending(a.status));
  return (
    <div className="app approver">
      <header className="top">
        <span className="logo" aria-hidden="true">V</span>
        <strong className="title">Valio Aimo <span>Approvals</span></strong>
        <span className="who">{me.display_name}</span>
        <button type="button" className="small" onClick={onSignOut}>Sign out</button>
      </header>
      <main className="console">
        <h1>Waiting for you {data && <span className="count">{pending.length}</span>}</h1>
        <p className="notice" role="note">
          You decide here, on your own device. Nobody can approve by voice or through an AI agent.
        </p>
        <div ref={latestRef} tabIndex={-1} role="status" aria-live="polite" className="latest">
          {latest && <Result r={latest} />}
        </div>
        {error && <p className="card error" role="alert">Could not load the requests: {error}</p>}
        {!data && !error && <p className="card">Loading requests…</p>}
        {data && pending.length === 0 && (
          <p className="card empty">Nothing is waiting. New requests show up here within 2 seconds.</p>
        )}
        {pending.map((a) => (
          <PendingItem key={a.approval_id} a={a} result={results[a.approval_id]} highlight={a.approval_id === focusId}
                       onDecided={onDecided} />
        ))}
        {decided.length > 0 && (
          <details className="decided">
            <summary>Decided ({decided.length})</summary>
            <ul>{decided.map((a) => <DecidedItem key={a.approval_id} a={a} result={results[a.approval_id]} />)}</ul>
          </details>
        )}
      </main>
    </div>
  );
}
