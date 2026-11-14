/**
 * The basket in focus (docs/basket-plan.md M23, M24a): one row per line, the gateway's totals and counts, and one
 * quote for all. Every field is a control: the product opens its details, the amount and the date edit in place,
 * × removes with Undo. Edits go to the gateway and the card renders its answer; it computes no number itself.
 */
import { useEffect, useState } from "react";
import { api, errorText, eur, helsinki, type Basket, type BasketLine, type Offer } from "../api";
import { BASKET_TOOLS } from "../cow/mood";
import { personaName } from "../persona";
import { focusBasket, receiveBasket, showQuote, showToast, ui, useUi } from "../voice/store";
import { applyBasket, hasBasket, quoteBasketNow, restoreLine } from "./actions";
import {
  buildPatch, chipFlags, countsText, flagLabel, flagNote, formatAmount, lineDomId, needsAttention, refusal, statusLabel,
  type LineChange,
} from "./basket";
import { DateEditor, QtyEditor, type PatchFn } from "./Editors";
import { ProductButton } from "./ProductDetails";

/** What the gateway says the line orders: units needed (offer.qty × offer.api_unit) and the overshoot. */
function GatewayUnits({ l }: { l: BasketLine }) {
  if (!l.offer) return null;
  const over = l.overshoot !== null && Number(l.overshoot) > 0;
  return (
    <small className="units">
      = {l.offer.qty} × {l.offer.api_unit}
      {over && <> · {l.overshoot} {l.unit ?? ""} over</>}
    </small>
  );
}

/** The cut-off for the chosen offer, or the gateway's message when the cut-off has passed. */
function GatewayDate({ l }: { l: BasketLine }) {
  if (l.status === "cutoff_passed") return <small className="warn">{l.message.en}</small>;
  if (!l.offer) return null;
  return (
    <small className="units">
      order by {helsinki(l.offer.order_by)}
      {l.offer.delivery_date !== l.need_date && <> · delivers {l.offer.delivery_date}</>}
    </small>
  );
}

function ProductCell({ l, onUse }: { l: BasketLine; onUse?: (o: Offer) => Promise<string | null> }) {
  const name = l.name_fi ?? l.need_text;
  const clickable = l.product_id !== null || l.alternatives.length > 0;
  return (
    <>
      {clickable ? (
        <ProductButton label={l.product_id ? name : `Choose: ${name}`} className="pname" productId={l.product_id}
                       offer={l.offer} flags={l.flags} flagNotes={l.flag_notes} alternatives={l.alternatives}
                       onUse={onUse} />
      ) : (
        <strong className="pname">{name}</strong>
      )}
      {l.name_fi && l.need_text && <span className="need">for “{l.need_text}”</span>}
    </>
  );
}

type RowProps = {
  l: BasketLine; readOnly: boolean; open: boolean; removing: boolean; onRemove: (l: BasketLine) => void;
  onPatch: (l: BasketLine) => PatchFn;
};

function LineRow({ l, readOnly, open, removing, onRemove, onPatch }: RowProps) {
  const attention = needsAttention(l.status);
  const patch = onPatch(l);
  const use = readOnly ? undefined : (o: Offer) => patch({ offer_id: o.offer_id });
  return (
    <tr id={lineDomId(l.line_id)} role="row" tabIndex={-1}
        className={`line${attention ? " attention" : ""}${open ? " open" : ""}`}>
      <td role="cell" className="no"><span className="sr-only">Line </span>{l.line_id}</td>
      <td role="cell" className="prod">
        <ProductCell l={l} onUse={use} />
        <ul className="flags" aria-label={`Status and flags of line ${l.line_id}`}>
          <li className={`st st-${l.status}`}>{statusLabel(l.status)}</li>
          {chipFlags(l).map((f) => <li key={f} title={flagNote(l, f) || undefined}>{flagLabel(f)}</li>)}
        </ul>
        {attention && l.status !== "cutoff_passed" && l.message.en && <p className="line-msg">{l.message.en}</p>}
      </td>
      <td role="cell" className="amt" data-label="Amount">
        {readOnly ? (
          <span className="qty-read">{l.amount === null ? "—" : `${formatAmount(l.amount)} ${l.unit ?? ""}`}</span>
        ) : (
          <QtyEditor l={l} onPatch={patch} />
        )}
        <GatewayUnits l={l} />
      </td>
      <td role="cell" className="date" data-label="Delivery">
        {readOnly ? <span className="date-read">{l.need_date}</span> : <DateEditor l={l} onPatch={patch} />}
        <GatewayDate l={l} />
      </td>
      <td role="cell" className="num" data-label="Line total excl. VAT">
        {l.status === "priced" && l.offer ? eur(l.offer.total_net) : <span aria-label="not priced">—</span>}
      </td>
      {!readOnly && (
        <td role="cell" className="rm">
          <button type="button" className="icon" aria-label={`Remove line ${l.line_id}`} aria-busy={removing}
                  disabled={removing} onClick={() => onRemove(l)}>×</button>
        </td>
      )}
    </tr>
  );
}

function Totals({ b }: { b: Basket }) {
  const partial = b.lines.some((l) => needsAttention(l.status));
  return (
    <>
      <dl className="totals">
        <div><dt>Total excl. VAT</dt><dd>{eur(b.total_net)}</dd></div>
        <div><dt>VAT</dt><dd>{eur(b.total_vat)}</dd></div>
        <div className="total"><dt>Total incl. VAT</dt><dd>{eur(b.total_gross)}</dd></div>
      </dl>
      <p className="muted counts">
        {countsText(b.counts)}
        {partial && " · Only priced lines are in the total."}
      </p>
    </>
  );
}

export function BasketCard() {
  const basketId = useUi((s) => s.basketId);
  const basket = useUi((s) => (s.basket && s.basket.basket_id === s.basketId ? s.basket : null));
  const alert = useUi((s) => (s.basketAlert && s.basketAlert.basketId === s.basketId ? s.basketAlert : null));
  const quoteId = useUi((s) => s.quoteId);
  const name = personaName(useUi((s) => s.persona));
  // The agent changed the basket on the gateway: fetch it again.
  const agentChange = useUi((s) => (s.lastOutcome && BASKET_TOOLS.has(s.lastOutcome.tool) ? s.lastOutcome.at : 0));
  const [loadError, setLoadError] = useState<string | null>(null);
  const [quoting, setQuoting] = useState(false);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<number | null>(null);

  useEffect(() => {
    if (!basketId) return;
    let alive = true;
    setLoadError(null);
    api.basket(basketId).then(
      (r) => {
        if (alive && hasBasket(r)) ui.set((s) => receiveBasket(s, r.basket));
      },
      (e: unknown) => {
        if (alive) setLoadError(errorText(e));
      },
    );
    return () => {
      alive = false;
    };
  }, [basketId, agentChange]);

  useEffect(() => setQuoteError(null), [basketId]);

  if (!basketId) return null;
  const startNew = () => ui.set((s) => focusBasket(s, null));
  if (!basket) {
    if (!loadError) return <p className="card">Loading basket…</p>;
    return (
      <section className="card basket" aria-label="Basket">
        <p className="error">Could not load basket {basketId}: {loadError}</p>
        <button type="button" onClick={startNew}>Start a new basket</button>
      </section>
    );
  }

  const b = basket;
  const ordered = b.status === "ordered";
  const open = (l: BasketLine) => !!alert && alert.lines.includes(l.line_id) && needsAttention(l.status);

  /** PATCH one line with all four fields; the gateway prices it again and the row shows its answer. */
  const patchLine = (l: BasketLine): PatchFn => async (change: LineChange) => {
    try {
      const r = await api.patchLine(b.basket_id, l.line_id, buildPatch(change));
      applyBasket(r);
      return refusal(r);
    } catch (e) {
      return errorText(e);
    }
  };

  const remove = async (l: BasketLine) => {
    setRemoving(l.line_id);
    try {
      const r = await api.removeLine(b.basket_id, l.line_id);
      const refused = refusal(r);
      if (refused) {
        applyBasket(r);
        ui.set(showToast(refused));
        return;
      }
      // One update: the row goes and the toast with Undo comes, so focus can move to Undo.
      const basketOf = b.basket_id;
      ui.set((s) => ({
        ...(hasBasket(r) ? receiveBasket(s, r.basket) : {}),
        ...showToast(`Removed line ${l.line_id}.`, { label: "Undo", run: () => void restoreLine(basketOf, l.line_id) }),
      }));
    } catch (e) {
      ui.set(showToast(`Could not remove line ${l.line_id}: ${errorText(e)}`));
    } finally {
      setRemoving(null);
    }
  };

  const getQuote = async () => {
    setQuoting(true);
    setQuoteError(null);
    try {
      const r = await quoteBasketNow(b.basket_id);
      if (r.reason_code !== "basket_incomplete" && !r.quote_id) setQuoteError(r.message_for_user.en || "No quote came back.");
    } catch (e) {
      setQuoteError(errorText(e));
    } finally {
      setQuoting(false);
    }
  };

  const showSaved = () => ui.set((s) => showQuote(s, b.quote_id, b.basket_id));

  return (
    <section className={`card basket${ordered ? " ordered" : ""}`} aria-labelledby="basket-title">
      <header>
        <span className="tier">{ordered ? "Ordered" : "Basket"}</span>
        <span className="pid">{b.basket_id}</span>
      </header>
      <h2 id="basket-title" tabIndex={-1}>
        Your basket · {b.lines.length === 1 ? "1 line" : `${b.lines.length} lines`}
      </h2>
      {ordered ? (
        <div className="locked" role="note">
          <p><strong>Ordered.</strong> This basket is read-only now. Start a new basket to order more.</p>
          <button type="button" onClick={startNew}>Start a new basket</button>
        </div>
      ) : (
        b.lines.length > 0 && (
          <p className="hint">Click a product for its details, or change an amount or a date: the gateway prices the line again.</p>
        )
      )}
      {b.lines.length === 0 ? (
        <p className="muted">The basket is empty. Tell {name} what you need, or add an option card.</p>
      ) : (
        <table className="lines" role="table" aria-label={`Lines of basket ${b.basket_id}`}>
          <thead role="rowgroup">
            <tr role="row">
              <th role="columnheader" scope="col" className="no">#</th>
              <th role="columnheader" scope="col">Product</th>
              <th role="columnheader" scope="col">Amount</th>
              <th role="columnheader" scope="col">Delivery</th>
              <th role="columnheader" scope="col" className="num">Line total excl. VAT</th>
              {!ordered && <th role="columnheader" scope="col" className="rm"><span className="sr-only">Remove</span></th>}
            </tr>
          </thead>
          <tbody role="rowgroup">
            {b.lines.map((l) => (
              <LineRow key={l.line_id} l={l} readOnly={ordered} open={open(l)} removing={removing === l.line_id}
                       onRemove={(x) => void remove(x)} onPatch={patchLine} />
            ))}
          </tbody>
        </table>
      )}
      <Totals b={b} />
      {alert && (
        <p className="alert" role="alert">
          {alert.message}
          {alert.lines.length > 0 && ` Lines to resolve: ${alert.lines.join(", ")}.`}
        </p>
      )}
      {b.quote_id && b.quote_stale && !ordered && (
        <p className="warn-box">Quote {b.quote_id} is out of date: the basket changed after it. Get a new quote below.</p>
      )}
      {!ordered && (
        <div className="actions">
          <button type="button" className="primary" disabled={quoting || b.lines.length === 0} aria-busy={quoting}
                  onClick={() => void getQuote()}>
            {quoting ? "Getting the quote…" : "Get one quote for all"}
          </button>
          {b.quote_id && !b.quote_stale && quoteId !== b.quote_id && (
            <button type="button" onClick={showSaved}>Show quote {b.quote_id}</button>
          )}
        </div>
      )}
      {quoteError && <p className="error" role="alert">{quoteError}</p>}
    </section>
  );
}
