import { useEffect, useRef, useState, type ReactNode } from "react";
import { useConversationControls } from "@elevenlabs/react";
import { api, errorText, eur, helsinki, type Offer, type OrderResponse, type QuoteLine } from "../api";
import { personaName } from "../persona";
import { answerConfirmation } from "../voice/ClientTools";
import { basketNote, quoteNote } from "../voice/notes";
import { focusBasket, quoteLoaded, showToast, ui, useUi } from "../voice/store";
import { useAgentNote } from "../voice/useAgentNote";
import { applyBasket, hasBasket, quoteBasketNow, refreshBasket } from "./actions";
import { flagLabel, orderRequestMessage, quoteIsStale, refusal } from "./basket";
import { ProductButton } from "./ProductDetails";
import { useFetch } from "./useFetch";

const TIER_TEXT = { best: "Best", better: "Better", good: "Good", other: "Also on time" } as const;

type CardProps = { o: Offer; chosen: boolean; onSelect: (o: Offer) => void; action: ReactNode };

/** Clicking the card selects it (aria-pressed on its tier toggle); its button adds it to the basket. */
function OfferCard({ o, chosen, onSelect, action }: CardProps) {
  return (
    <article className={`card offer tier-${o.tier}${chosen ? " chosen" : ""}`}
             onClick={(e) => { if (!(e.target as HTMLElement).closest("button, .pop-panel")) onSelect(o); }}>
      <header>
        <button type="button" className="tier pick" aria-pressed={chosen} aria-label={`Select the ${TIER_TEXT[o.tier]} option`}
                onClick={() => onSelect(o)}>
          {chosen ? "✓ " : ""}{TIER_TEXT[o.tier]}
        </button>
        <span className="pid">{o.product_id}</span>
      </header>
      <h3><ProductButton label={o.name_fi} productId={o.product_id} offer={o} /></h3>
      <p className="big">{eur(o.total_net)} <small>excl. VAT</small></p>
      <p>{o.qty} × {o.api_unit} · {o.price_per_base_unit} €/{o.base_unit.toLowerCase()}</p>
      <p>Delivery {o.delivery_date} · order by {helsinki(o.order_by)}</p>
      <ul className="flags">{o.flags.map((f) => <li key={f}>{flagLabel(f)}</li>)}</ul>
      {action}
    </article>
  );
}

/**
 * The options of one offer set. "Add to basket" puts an option into the basket in focus (or starts one);
 * when the agent showed them for a line (show_products line_id), the button replaces that line instead.
 */
export function OfferCards() {
  const id = useUi((s) => s.offerSetId);
  const basketId = useUi((s) => s.basketId);
  const replace = useUi((s) => (s.replaceLine && s.replaceLine.basketId === s.basketId ? s.replaceLine : null));
  const { data, error } = useFetch(id, api.offerSet);
  const [chosen, setChosen] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [added, setAdded] = useState<Record<string, number>>({});
  const notify = useAgentNote(); // during a call, the agent hears about the change
  useEffect(() => {
    setChosen(null); // a new search starts a new choice
    setAdded({});
  }, [id]);
  if (!id) return null;
  if (error) return <p className="card error">Could not load the options: {error}</p>;
  if (!data || data.offer_set_id !== id) return <p className="card">Loading options…</p>;

  const put = async (o: Offer, newBasket = false) => {
    if (busy) return;
    setChosen(o.offer_id);
    setBusy(o.offer_id);
    const target = newBasket ? null : replace;
    try {
      const r = await api.addFromOffer(newBasket ? null : basketId, o.offer_id, target?.lineId ?? 0);
      if (r.reason_code === "basket_locked") {
        applyBasket(r); // the card turns read-only
        ui.set(showToast(r.message_for_user.en || "That basket is already ordered.", {
          label: "Add to a new basket", run: () => void put(o, true),
        }));
        return;
      }
      const refused = refusal(r);
      if (refused || !hasBasket(r)) {
        ui.set(showToast(refused ?? "The basket did not change."));
        return;
      }
      const lineId = r.line?.line_id ?? target?.lineId ?? null;
      ui.set((s) => ({
        ...focusBasket(s, r.basket_id, r.basket),
        ...(target ? { replaceLine: null } : {}),
        ...showToast(target ? `Replaced line ${target.lineId}.` : lineId ? `Added as line ${lineId}.` : "Added to the basket."),
      }));
      if (lineId !== null) {
        setAdded((a) => ({ ...a, [o.offer_id]: lineId }));
        notify(basketNote(target ? "replace" : "add", lineId, r.basket, r.line));
      }
    } catch (e) {
      ui.set(showToast(`Could not add it to the basket: ${errorText(e)}`));
    } finally {
      setBusy(null);
    }
  };

  const action = (o: Offer, small = false) => {
    const done = added[o.offer_id];
    const label = busy === o.offer_id ? (replace ? "Replacing…" : "Adding…")
      : done !== undefined ? `✓ In basket, line ${done}`
      : replace ? `Replace line ${replace.lineId}` : "Add to basket";
    return (
      <button type="button" className={`choose${small ? " small" : ""}`} disabled={busy !== null || done !== undefined}
              aria-busy={busy === o.offer_id} onClick={() => void put(o)}>
        {label}
      </button>
    );
  };

  const select = (o: Offer) => setChosen((c) => (c === o.offer_id ? null : o.offer_id));
  const top = data.options.filter((o) => o.tier !== "other");
  const more = data.options.filter((o) => o.tier === "other");
  return (
    <section aria-label="Options" className="cards">
      <h2>{replace ? `Options for line ${replace.lineId}` : "Options"} · delivery {data.options[0]?.delivery_date ?? ""}</h2>
      {replace ? (
        <p className="hint">
          Replace line {replace.lineId} swaps its product and keeps the line.{" "}
          <button type="button" className="small" onClick={() => ui.set({ replaceLine: null })}>Add as a new line instead</button>
        </p>
      ) : (
        <p className="hint">Click an option to select it, then add it to your basket. Or just say which one you want.</p>
      )}
      <div className="row">
        {top.map((o) => (
          <OfferCard key={o.offer_id} o={o} chosen={chosen === o.offer_id} onSelect={select} action={action(o)} />
        ))}
      </div>
      {more.length > 0 && (
        <details>
          <summary>More on-time options ({more.length})</summary>
          <ul className="more">
            {more.map((o) => (
              <li key={o.offer_id} className={chosen === o.offer_id ? "chosen" : ""}>
                <span>
                  <ProductButton label={o.name_fi} productId={o.product_id} offer={o} /> · {o.qty} × {o.api_unit} ·{" "}
                  {eur(o.total_net)} excl. VAT
                </span>
                {action(o, true)}
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

/** A quote line's price as the gateway fixed it: unit price × quantity, VAT and gross. */
function QuoteLineFacts({ l }: { l: QuoteLine }) {
  return (
    <dl className="facts">
      <div><dt>In this quote</dt><dd>{l.qty} × {l.api_unit} at {eur(l.unit_price_net)} = {eur(l.line_net)} excl. VAT</dd></div>
      <div><dt>VAT {l.vat_rate} %</dt><dd>{eur(l.line_vat)} · {eur(l.line_gross)} incl. VAT</dd></div>
      <div><dt>Delivery</dt><dd>{l.delivery_date}</dd></div>
    </dl>
  );
}

/**
 * The fixed-price quote. During a call the agent asks for confirmation (request_buyer_confirmation) and places the
 * order itself, so the screen only answers it. With no call running, the screen confirms and orders on its own.
 */
export function QuoteCard({ onAsk }: { onAsk: (text: string) => void }) {
  const id = useUi((s) => s.quoteId);
  const confirmId = useUi((s) => s.confirmQuoteId);
  const callActive = useUi((s) => s.phase === "live" || s.phase === "connecting");
  const basket = useUi((s) => s.basket);
  const order = useUi((s) => (s.order && s.order.quoteId === s.quoteId ? s.order : null));
  const name = personaName(useUi((s) => s.persona));
  const { data, error, reload } = useFetch(id, api.quote);
  const q = data && data.quote_id === id ? data : null;
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [staleHere, setStaleHere] = useState(false); // the gateway answered quote_stale
  const [orderFailed, setOrderFailed] = useState(false); // confirmed here, but the order call failed
  const notify = useAgentNote();
  useEffect(() => {
    setMsg(null);
    setStaleHere(false);
    setOrderFailed(false);
  }, [id]);
  useEffect(() => {
    if (q) ui.set((s) => quoteLoaded(s, q));
  }, [q]);
  if (!id) return null;
  if (error) return <p className="card error">Could not load the quote: {error}</p>;
  if (!q) return <p className="card">Loading quote…</p>;

  const stale = staleHere || quoteIsStale(q, basket);
  const asking = confirmId === q.quote_id;
  const run = async (f: () => Promise<void>) => {
    setBusy(true);
    setMsg(null);
    try {
      await f();
    } catch (e) {
      setMsg(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  // During a call: answer the agent, which then calls place_order itself.
  const answer = (yes: boolean) => run(async () => {
    const r = await answerConfirmation(q.quote_id, yes);
    if (r?.reason_code === "quote_stale") setStaleHere(true);
    if (r && !r.confirmed) setMsg(r.message_for_user.en);
    if (r?.confirmed) reload();
  });

  // No call running: POST /v1/orders from the screen. Never during a call (two callers would make two orders).
  const placeOrder = async () => {
    const phase = ui.get().phase;
    if (phase === "live" || phase === "connecting") {
      setMsg(`Confirmed. ${name} places the order during the call.`);
      return;
    }
    let o: OrderResponse;
    try {
      o = await api.placeOrder(q.quote_id);
    } catch (e) {
      setOrderFailed(true);
      throw new Error(`Confirmed, but the order did not go through: ${errorText(e)}`);
    }
    setOrderFailed(false);
    if (o.reason_code === "quote_stale") {
      setStaleHere(true);
      setMsg(o.message_for_user.en);
    } else if (o.status === "completed" || o.status === "requires_escalation") {
      ui.set({
        order: { quoteId: q.quote_id, orderId: o.order_id, status: o.status, message: o.message_for_user },
        ...(o.status === "requires_escalation" && o.approval_id ? { approvalId: o.approval_id } : {}),
      });
    } else {
      setMsg(o.message_for_user.en);
    }
    if (q.basket_id) void refreshBasket(q.basket_id);
  };

  const confirmHere = () => run(async () => {
    const c = await api.confirm(q.quote_id);
    if (c.reason_code === "quote_stale") {
      setStaleHere(true);
      setMsg(c.message_for_user.en);
      return;
    }
    if (!c.confirmed) {
      setMsg(c.message_for_user.en);
      return;
    }
    reload();
    await placeOrder();
  });

  const newQuote = () => run(async () => {
    if (!q.basket_id) return;
    const r = await quoteBasketNow(q.basket_id);
    notify(quoteNote(r));
    if (!r.quote_id) setMsg(r.message_for_user.en || "No quote came back.");
  });

  const dates = new Set(q.lines.map((l) => l.delivery_date));
  const own = !callActive && !asking; // the screen confirms and orders by itself
  return (
    <section className={`card quote${stale ? " stale" : ""}`} id={`quote-${q.quote_id}`} tabIndex={-1}
             aria-labelledby={`quote-${q.quote_id}-title`}>
      <header>
        <span className="tier" id={`quote-${q.quote_id}-title`}>Fixed-price quote</span>
        <span className="pid">{q.quote_id}</span>
      </header>
      {q.basket_id && (
        <p className="for">
          For basket <code>{q.basket_id}</code>
          {q.basket_version !== null && <> · version {q.basket_version}</>} · one quote for every line
        </p>
      )}
      <table>
        <tbody>
          {q.lines.map((l) => {
            // The basket line this quote line priced, while the quote still holds: its offer and flags.
            const bl = !stale && q.basket_id && basket?.basket_id === q.basket_id
              ? basket.lines.find((x) => x.line_id === l.line_id && x.product_id === l.product_id) : undefined;
            return (
              <tr key={l.line_id}>
                <td className="qty">{l.qty} × {l.api_unit}</td>
                <td>
                  {q.basket_id && <span className="sub">Line {l.line_id}</span>}
                  <ProductButton label={l.name_fi} productId={l.product_id} offer={bl?.offer ?? null} flags={bl?.flags ?? []}
                                 flagNotes={bl?.flag_notes ?? []} extra={<QuoteLineFacts l={l} />} />
                  <span className="sub">Delivery {l.delivery_date}</span>
                </td>
                <td className="num">{eur(l.line_net)}</td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr><td colSpan={2}>Total excl. VAT</td><td className="num">{eur(q.total_net)}</td></tr>
          <tr><td colSpan={2}>VAT</td><td className="num">{eur(q.total_vat)}</td></tr>
          <tr className="total"><td colSpan={2}>Total incl. VAT</td><td className="num">{eur(q.total_gross)}</td></tr>
        </tfoot>
      </table>
      <p>
        {dates.size > 1 ? "First delivery" : "Delivery"} {q.delivery_date} · price fixed until {helsinki(q.expires_at)}
      </p>
      <p className="muted">{q.quote_jws ? "Signed (JWS ES256)" : "Not signed yet: contract stub (M6 adds the signature)"}</p>
      {q.confirmed && <p className="ok">Confirmed by you</p>}
      {order && (
        <p className={order.status === "completed" ? "ok" : "note"} role="status">
          {order.status === "completed" && order.orderId ? `Order ${order.orderId} placed. ` : ""}
          {order.message.en}
        </p>
      )}
      {stale && !order && (
        <div className="stale-box" role="alert">
          <p><strong>Out of date.</strong> The basket changed after this quote, so its prices no longer hold.</p>
          {q.basket_id && (
            <button type="button" className="primary" disabled={busy} aria-busy={busy} onClick={() => void newQuote()}>
              Make a new quote
            </button>
          )}
        </div>
      )}
      {asking && !stale && (
        <div className="confirm" role="group" aria-label="Confirm the order">
          <button type="button" className="primary" disabled={busy} onClick={() => void answer(true)}>Confirm order</button>
          <button type="button" disabled={busy} onClick={() => void answer(false)}>Not now</button>
        </div>
      )}
      {own && !q.confirmed && !stale && !order && (
        <div className="confirm calm" role="group" aria-label="Confirm the order">
          <button type="button" className="primary" disabled={busy} aria-busy={busy} onClick={() => void confirmHere()}>
            {busy ? "Confirming…" : "Confirm order"}
          </button>
          <span>One confirmation orders every line of this quote.</span>
        </div>
      )}
      {own && q.confirmed && !stale && !order && orderFailed && (
        <button type="button" className="primary" disabled={busy} aria-busy={busy} onClick={() => void run(placeOrder)}>
          Place the order
        </button>
      )}
      {callActive && !asking && !q.confirmed && !stale && (
        <p className="hint">
          {name} asks you to confirm here before ordering.{" "}
          <button type="button" className="small" onClick={() => onAsk(orderRequestMessage(q.quote_id))}>
            Ask {name} to order
          </button>
        </p>
      )}
      {msg && <p className="error" role="alert">{msg}</p>}
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
