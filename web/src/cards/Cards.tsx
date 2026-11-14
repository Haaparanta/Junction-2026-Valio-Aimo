import { useEffect, useRef, useState } from "react";
import { useConversationControls } from "@elevenlabs/react";
import { api, eur, helsinki, type Offer } from "../api";
import { answerConfirmation } from "../voice/ClientTools";
import { useUi } from "../voice/store";
import { useFetch } from "./useFetch";

const FLAG_TEXT: Record<string, string> = {
  STOCK_UNTRACKED: "stock not tracked", NET_PRICE: "your contract price", VARIANT: "variant", CUTOFF_PASSED: "cut-off passed",
  PARTIAL_STOCK: "partial stock", NOT_DELIVERABLE: "not deliverable", UNIT_MISMATCH: "unit differs from catalogue",
};
const TIER_TEXT = { best: "Best", better: "Better", good: "Good", other: "Also on time" } as const;

/** What a click sends to the agent: the choice and its id, never a price (prices come only from the gateway). */
export function choiceMessage(o: Offer): string {
  const tier = o.tier === "other" ? "this" : `the ${TIER_TEXT[o.tier].toLowerCase()}`;
  return `I choose ${tier} option: ${o.name_fi}, ${o.qty} × ${o.api_unit} (offer_id ${o.offer_id}).`;
}

type ChooseProps = { chosen: boolean; busy: boolean; onChoose: (o: Offer) => void };

function OfferCard({ o, chosen, busy, onChoose }: { o: Offer } & ChooseProps) {
  return (
    <article className={`card offer tier-${o.tier}${chosen ? " chosen" : ""}`}
             onClick={(e) => { if (!busy && !(e.target as HTMLElement).closest("button")) onChoose(o); }}>
      <header>
        <span className="tier">{TIER_TEXT[o.tier]}</span>
        <span className="pid">{o.product_id}</span>
      </header>
      <h3>{o.name_fi}</h3>
      <p className="big">{eur(o.total_net)} <small>excl. VAT</small></p>
      <p>{o.qty} × {o.api_unit} · {o.price_per_base_unit} €/{o.base_unit.toLowerCase()}</p>
      <p>Delivery {o.delivery_date} · order by {helsinki(o.order_by)}</p>
      <ul className="flags">{o.flags.map((f) => <li key={f}>{FLAG_TEXT[f] ?? f}</li>)}</ul>
      <button className="choose" disabled={busy} aria-pressed={chosen} onClick={() => onChoose(o)}>
        {chosen ? "✓ Chosen" : "Choose this option"}
      </button>
    </article>
  );
}

export function OfferCards({ onChoose }: { onChoose: (text: string) => void }) {
  const id = useUi((s) => s.offerSetId);
  const { data, error } = useFetch(id, api.offerSet);
  const [chosen, setChosen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => setChosen(null), [id]); // a new search starts a new choice
  if (!id) return null;
  if (error) return <p className="card error">Could not load the options: {error}</p>;
  if (!data) return <p className="card">Loading options…</p>;
  const choose = (o: Offer) => {
    if (busy) return;
    setChosen(o.offer_id);
    setBusy(true); // guard against double clicks sending the choice twice
    setTimeout(() => setBusy(false), 2500);
    onChoose(choiceMessage(o));
  };
  const top = data.options.filter((o) => o.tier !== "other");
  const more = data.options.filter((o) => o.tier === "other");
  return (
    <section aria-label="Options" className="cards">
      <h2>Options for delivery {data.options[0]?.delivery_date ?? ""}</h2>
      <p className="hint">Click an option to choose it, or just say which one you want.</p>
      <div className="row">
        {top.map((o) => <OfferCard key={o.offer_id} o={o} chosen={chosen === o.offer_id} busy={busy} onChoose={choose} />)}
      </div>
      {more.length > 0 && (
        <details>
          <summary>More on-time options ({more.length})</summary>
          <ul className="more">
            {more.map((o) => (
              <li key={o.offer_id} className={chosen === o.offer_id ? "chosen" : ""}>
                <span><strong>{o.name_fi}</strong> · {o.qty} × {o.api_unit} · {eur(o.total_net)} excl. VAT</span>
                <button className="choose small" disabled={busy} aria-pressed={chosen === o.offer_id} onClick={() => choose(o)}>
                  {chosen === o.offer_id ? "✓ Chosen" : "Choose"}
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
      {data.not_offered.length > 0 && (
        <details>
          <summary>Not offered ({data.not_offered.length})</summary>
          <ul>{data.not_offered.map((n) => <li key={n.product_id}>{n.name_fi}: {n.reason.en}</li>)}</ul>
        </details>
      )}
    </section>
  );
}

export function QuoteCard() {
  const id = useUi((s) => s.quoteId);
  const confirmId = useUi((s) => s.confirmQuoteId);
  const { data: q, error } = useFetch(id, api.quote);
  const [busy, setBusy] = useState(false);
  if (!id) return null;
  if (error) return <p className="card error">Could not load the quote: {error}</p>;
  if (!q) return <p className="card">Loading quote…</p>;
  const asking = confirmId === q.quote_id;
  const answer = async (yes: boolean) => {
    setBusy(true);
    try {
      await answerConfirmation(q.quote_id, yes);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="card quote" aria-label="Quote">
      <header><span className="tier">Fixed-price quote</span><span className="pid">{q.quote_id}</span></header>
      <table>
        <tbody>
          {q.lines.map((l) => (
            <tr key={l.line_id}><td className="qty">{l.qty} × {l.api_unit}</td><td>{l.name_fi}</td><td className="num">{eur(l.line_net)}</td></tr>
          ))}
        </tbody>
        <tfoot>
          <tr><td colSpan={2}>Total excl. VAT</td><td className="num">{eur(q.total_net)}</td></tr>
          <tr><td colSpan={2}>VAT</td><td className="num">{eur(q.total_vat)}</td></tr>
          <tr className="total"><td colSpan={2}>Total incl. VAT</td><td className="num">{eur(q.total_gross)}</td></tr>
        </tfoot>
      </table>
      <p>Delivery {q.delivery_date} · price fixed until {helsinki(q.expires_at)}</p>
      <p className="muted">{q.quote_jws ? "Signed (JWS ES256)" : "Not signed yet: contract stub (M6 adds the signature)"}</p>
      {q.confirmed && <p className="ok">Confirmed by you</p>}
      {asking && !q.confirmed && (
        <div className="confirm" role="group" aria-label="Confirm the order">
          <button className="primary" disabled={busy} onClick={() => void answer(true)}>Confirm order</button>
          <button disabled={busy} onClick={() => void answer(false)}>Not now</button>
        </div>
      )}
    </section>
  );
}

const REASON_TEXT: Record<string, string> = {
  OVER_ORDER_CAP: "Over your order cap", OVER_BUDGET: "Over the weekly budget", SUBSTITUTION: "Includes a substitute",
  NET_ABOVE_LIST: "Contract price above list price", UNIT_MISMATCH: "Unit differs from the catalogue",
};

/** "OVER_ORDER_CAP: EUR 1010.00 is above ..." -> a plain title, the detail, and the code as a small tag. */
function Reason({ text }: { text: string }) {
  const [code = "", detail = ""] = text.split(/:\s*/, 2);
  const title = REASON_TEXT[code];
  if (!title) return <>{text}</>;
  return <><strong>{title}</strong> {detail} <code>{code}</code></>;
}

/** Polls the approval every 2 s; on a change, tells the agent silently and nudges it (PLAN M9.4). */
export function ApprovalCard() {
  const id = useUi((s) => s.approvalId);
  const live = useUi((s) => s.phase === "live");
  const { data: a, error } = useFetch(id, api.approval, 2000);
  const { sendContextualUpdate, sendUserMessage } = useConversationControls();
  const last = useRef<string | null>(null);
  useEffect(() => {
    if (!a) return;
    const prev = last.current;
    last.current = a.status;
    if (prev && prev !== a.status && live) {
      try {
        sendContextualUpdate(`Order ${a.approval.order_id} status changed to ${a.status} (approval ${a.approval_id}).`);
        sendUserMessage("Is there news about my order?");
      } catch { /* call ended */ }
    }
  }, [a, live, sendContextualUpdate, sendUserMessage]);
  if (!id) return null;
  if (error) return <p className="card error">Could not load the approval: {error}</p>;
  if (!a) return <p className="card">Loading approval…</p>;
  return (
    <section className={`card approval status-${a.status}`} aria-label="Approval">
      <header><span className="tier">Needs approval</span><span className="pid">{a.approval_id}</span></header>
      <p className="big">⏳ {a.message_for_user.en}</p>
      <ul className="reasons">{a.approval.reasons.map((r) => <li key={r}><Reason text={r} /></li>)}</ul>
      <p>Decide by {helsinki(a.approval.decide_by)} · approver: {a.approval.approver_role.replace("_", " ")}</p>
      <p className="muted">Approvals happen only on the manager's own console. Nobody can approve by voice.</p>
    </section>
  );
}
