/**
 * Behind every product name (basket line, option card, quote line; M24.4): the catalogue facts from
 * GET /v1/products/{id}, the line's offer and flags with the gateway's notes, and the alternatives with
 * "Use this instead". Everything shown is gateway data, rendered as text.
 */
import { useState, type ReactNode } from "react";
import { api, errorText, eur, helsinki, type FlagNote, type Offer } from "../api";
import { allergenLabel, claimLabel, flagLabel, TEMPERATURE_TEXT } from "./basket";
import { Popover } from "./Popover";
import { useFetch } from "./useFetch";

type DetailsProps = {
  /** null while a line has no product yet (needs_choice): then only the alternatives are shown. */
  productId: string | null;
  offer?: Offer | null;
  flags?: string[];
  flagNotes?: FlagNote[];
  alternatives?: Offer[];
  /** Switch the line to another offer; resolves to an error message, or null when the gateway took it. */
  onUse?: (o: Offer) => Promise<string | null>;
  /** Extra facts from the caller, such as a quote line's VAT. */
  extra?: ReactNode;
};

type ButtonProps = DetailsProps & { label: string; className?: string };

export function ProductButton({ label, className, ...details }: ButtonProps) {
  return (
    <Popover label={label} title={label} triggerClass={`link${className ? ` ${className}` : ""}`}
             triggerLabel={`${label}: details`}>
      {(close) => <ProductDetails {...details} close={close} />}
    </Popover>
  );
}

function ProductDetails({ productId, offer, flags, flagNotes = [], alternatives = [], onUse, extra, close }:
  DetailsProps & { close: () => void }) {
  const { data, error } = useFetch(productId, api.product);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const p = data?.product && data.product.product_id === productId ? data.product : null;
  const shownFlags = flags ?? offer?.flags ?? [];
  const note = (code: string) => flagNotes.find((n) => n.code === code)?.text.en ?? "";

  const use = async (o: Offer) => {
    if (!onUse || busy) return;
    setBusy(o.offer_id);
    setErr(null);
    try {
      const e = await onUse(o);
      if (e) setErr(e);
      else close();
    } catch (x) {
      setErr(errorText(x));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="details">
      {productId && !p && !error && <p className="muted">Loading product details…</p>}
      {error && <p className="error">Could not load the product details: {error}</p>}
      {p && (
        <dl className="facts">
          <div><dt>Product id</dt><dd><code>{p.product_id}</code>{p.brand ? ` · ${p.brand}` : ""}</dd></div>
          <div>
            <dt>Content per unit</dt>
            <dd>{p.content_per_unit ? `${p.content_per_unit.value} ${p.content_per_unit.unit} per ${p.sales_unit}` : "not known"}</dd>
          </div>
          <div><dt>Claims</dt><dd>{p.claims.length ? p.claims.map(claimLabel).join(", ") : "none"}</dd></div>
          <div>
            <dt>Allergens</dt>
            <dd>
              {p.allergen_data === "unknown" ? "not declared: check the package"
                : p.allergens_contains.length ? `contains ${p.allergens_contains.map(allergenLabel).join(", ")}` : "none declared"}
            </dd>
          </div>
          <div><dt>Temperature</dt><dd>{TEMPERATURE_TEXT[p.temperature_class] ?? p.temperature_class}</dd></div>
        </dl>
      )}
      {offer && (
        <dl className="facts">
          <div>
            <dt>Price per {offer.base_unit.toLowerCase()}</dt>
            <dd>{offer.price_per_base_unit} €/{offer.base_unit.toLowerCase()} excl. VAT</dd>
          </div>
          <div><dt>Unit price</dt><dd>{eur(offer.unit_price_net)} per {offer.api_unit}</dd></div>
          <div><dt>Ordered</dt><dd>{offer.qty} × {offer.api_unit} ({offer.content_total} {offer.base_unit})</dd></div>
          <div><dt>Delivery</dt><dd>{offer.delivery_date}, order by {helsinki(offer.order_by)}</dd></div>
        </dl>
      )}
      {extra}
      {shownFlags.length > 0 && (
        <ul className="flag-notes" aria-label="Flags">
          {shownFlags.map((f) => (
            <li key={f}><strong>{flagLabel(f)}</strong>{note(f) && <> · {note(f)}</>}</li>
          ))}
        </ul>
      )}
      {alternatives.length > 0 && (
        <section className="alts" aria-label={offer ? "Alternatives" : "Matching products"}>
          <h4>{offer ? "Alternatives" : "Matching products"}</h4>
          <ul>
            {alternatives.map((a) => (
              <li key={a.offer_id}>
                <span>
                  <strong>{a.name_fi}</strong> <code>{a.product_id}</code>
                  <span className="units">
                    {a.qty} × {a.api_unit} · {eur(a.total_net)} excl. VAT · {a.price_per_base_unit} €/{a.base_unit.toLowerCase()}
                    {a.flags.length > 0 && ` · ${a.flags.map(flagLabel).join(", ")}`}
                  </span>
                </span>
                {onUse && (
                  <button type="button" className="small" disabled={busy !== null} aria-busy={busy === a.offer_id}
                          onClick={() => void use(a)}>
                    {busy === a.offer_id ? "Switching…" : offer ? "Use this instead" : "Use this"}
                  </button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      {err && <p className="error" role="alert">{err}</p>}
    </div>
  );
}
