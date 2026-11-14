/**
 * The rest of click-to-edit (docs/basket-plan.md M24.7): the line total opens the gateway's price breakdown, the
 * ordered units open the API unit next to the catalogue unit, and every flag and status chip opens the gateway's
 * explanation and the next step. Each is a real <button> on the shared Popover (Enter or Space opens, Escape closes).
 * Every number is the gateway's, formatted only.
 */
import { api, eur, type BasketLine } from "../api";
import { chipInfo, flagLabel, priceBreakdown, statusLabel, unitView } from "./basket";
import { Popover } from "./Popover";
import { useFetch } from "./useFetch";

/** The line total excl. VAT; a click shows unit price × quantity, the VAT rate, the VAT and the gross. */
export function PricePopover({ l }: { l: BasketLine }) {
  const p = priceBreakdown(l);
  if (!p) return <span aria-label="not priced">—</span>;
  return (
    <Popover label={eur(p.totalNet)} title={`Price of line ${l.line_id}`} triggerClass="link num-link"
             triggerLabel={`${eur(p.totalNet)}: price breakdown of line ${l.line_id}`}>
      {() => (
        <dl className="facts">
          <div><dt>Unit price</dt><dd>{eur(p.unitPriceNet)} per {p.apiUnit} excl. VAT</dd></div>
          <div><dt>Quantity</dt><dd>{p.qty} × {p.apiUnit}</dd></div>
          <div><dt>Line total</dt><dd>{eur(p.totalNet)} excl. VAT</dd></div>
          <div><dt>VAT rate</dt><dd>{p.vatRate} %</dd></div>
          <div><dt>VAT</dt><dd>{eur(p.vat)}</dd></div>
          <div className="gross"><dt>Incl. VAT</dt><dd>{eur(p.gross)}</dd></div>
          <div><dt>Per {p.baseUnit.toLowerCase()}</dt><dd>{p.perBase} €/{p.baseUnit.toLowerCase()} excl. VAT</dd></div>
        </dl>
      )}
    </Popover>
  );
}

function UnitDetails({ l }: { l: BasketLine }) {
  const { data, error } = useFetch(l.product_id, api.product);
  const product = data?.product && data.product.product_id === l.product_id ? data.product : null;
  const v = unitView(l, product?.sales_unit ?? null);
  return (
    <div className="details">
      <dl className="facts">
        <div><dt>Ordered in</dt><dd>{v.apiUnit ?? "—"} <small>(the gateway's order unit)</small></dd></div>
        <div>
          <dt>Catalogue unit</dt>
          <dd>{product ? v.catalogueUnit : error ? "could not be loaded" : "loading…"}</dd>
        </div>
        {product?.content_per_unit && (
          <div>
            <dt>Content per unit</dt>
            <dd>{product.content_per_unit.value} {product.content_per_unit.unit} per {product.sales_unit}</dd>
          </div>
        )}
        {l.offer && <div><dt>Ordered</dt><dd>{l.offer.qty} × {l.offer.api_unit} ({l.offer.content_total} {l.offer.base_unit})</dd></div>}
      </dl>
      {v.mismatch && (
        <p className="flag-note-box"><strong>{flagLabel("UNIT_MISMATCH")}</strong>{v.note ? ` · ${v.note}` : ""}</p>
      )}
      {error && <p className="error">Could not load the catalogue unit: {error}</p>}
    </div>
  );
}

/** "= 40 × ST": what the gateway orders for the amount; a click shows the API unit and the catalogue unit. */
export function UnitPopover({ l }: { l: BasketLine }) {
  if (!l.offer) return null;
  const over = l.overshoot !== null && Number(l.overshoot) > 0;
  return (
    <span className="units">
      <Popover label={<>= {l.offer.qty} × {l.offer.api_unit}{l.flags.includes("UNIT_MISMATCH") ? " ⚠" : ""}</>}
               title={`Unit of line ${l.line_id}`} triggerClass="link units-link"
               triggerLabel={`= ${l.offer.qty} × ${l.offer.api_unit}: units of line ${l.line_id}`}>
        {() => (l.product_id ? <UnitDetails l={l} /> : <p className="muted">Choose a product first.</p>)}
      </Popover>
      {over && <> · {l.overshoot} {l.unit ?? ""} over</>}
    </span>
  );
}

/** One chip (code "status" for the status chip): its popover has the explanation and what to do next. */
export function ChipPopover({ l, code }: { l: BasketLine; code: string }) {
  const info = chipInfo(l, code);
  const label = code === "status" ? statusLabel(l.status) : flagLabel(code);
  return (
    <Popover label={label} title={info.title} triggerClass="chip-btn"
             triggerLabel={`${label}: ${code === "status" ? "status" : "flag"} of line ${l.line_id}, explanation`}>
      {() => (
        <div className="details">
          {info.explanation && <p className="chip-why">{info.explanation}</p>}
          {info.next && <p className="chip-next"><strong>Next step:</strong> {info.next}</p>}
          {code !== "status" && <p className="muted"><code>{code}</code></p>}
        </div>
      )}
    </Popover>
  );
}
