/**
 * Dish to basket (docs/basket-plan.md M27.2, M27.3): a dish, the servings, a delivery date and diet chips. The
 * gateway has the dish broken down into ingredients and adds each one to the basket, priced. Diet chips send claims
 * only (B-13); milk-free sends the allergen AM. Afterwards the card shows the dish header: the name, the servings,
 * the batch note, the warnings and the assumptions, all as the gateway sent them. Dish names are data: text only.
 */
import { useId, useRef, useState, type FormEvent } from "react";
import type { BasketDish, BasketLine, DishResponse } from "../api";
import {
  DIETS, MAX_DISH_CHARS, MAX_SERVINGS, buildDishRequest, dateOf, dishProblems, dishView, type DietKey, type DishField,
} from "./dish";
import { IntakeError, errorText, planDish } from "./intakeApi";
import "./imports.css";

export type DishFormProps = {
  /** The basket in focus; null starts a new basket. */
  basketId: string | null;
  /** The gateway's as-of time or date (Me.as_of); its date is the earliest delivery date the picker offers. */
  asOf: string;
  /** The language the buyer speaks; sent as the request's language. */
  language: "fi" | "en";
  /** Called with the gateway's answer once the dish is in the basket. */
  onPlanned: (response: DishResponse) => void;
  /** True while the basket must not change, for example while an order is being placed. */
  disabled?: boolean;
};

/**
 * A dish's header as the gateway planned it: in the dish card after Send, and on the basket card for each of
 * basket.dishes (M27.2). With `lines` (the basket's lines) it lists the dish's lines still in the basket, and with
 * `onShowLine` each is a button that shows its basket line.
 */
export function DishHeader({ dish, lines = null, onShowLine }: {
  dish: BasketDish; lines?: readonly BasketLine[] | null; onShowLine?: (lineId: number) => void;
}) {
  const v = dishView(dish, lines);
  return (
    <div className="intake-dish-head">
      <p className="intake-dish-name">
        {v.name}
        {v.nameFi && <span lang="fi"> · {v.nameFi}</span>}
      </p>
      <p className="intake-dish-meta">{v.meta}</p>
      {v.batchNote && <p>{v.batchNote}</p>}
      {v.warnings.length > 0 && (
        <div className="intake-warnings" role="note">
          <p className="intake-warn-head">Check before you order</p>
          <ul>{v.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
        </div>
      )}
      {v.assumptions.length > 0 && (
        <div className="intake-assumptions">
          <p className="intake-assume-head">Assumed</p>
          <ul>{v.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul>
        </div>
      )}
      {onShowLine && v.lineIds.length > 0 && (
        <p className="intake-dish-lines">
          Lines:{" "}
          {v.lineIds.map((id) => (
            <button key={id} type="button" className={`small${v.openLineIds.includes(id) ? " open-line" : ""}`}
                    aria-label={`Show line ${id}${v.openLineIds.includes(id) ? ", needs your attention" : ""}`}
                    onClick={() => onShowLine(id)}>
              {id}{v.openLineIds.includes(id) ? " !" : ""}
            </button>
          ))}
        </p>
      )}
    </div>
  );
}

/**
 * No dish came back (reason_code not_found: Claude refused, or found no ingredients). The gateway's message and its
 * warnings take the place of the dish header; nothing was added to the basket.
 */
export function NoDish({ response }: { response: DishResponse }) {
  return (
    <div className="intake-dish-head intake-no-dish" role="note">
      <p className="intake-dish-name">No dish was planned</p>
      <p>{response.message_for_user.en || "No ingredients came back for this dish. Nothing was added to the basket."}</p>
      {response.warnings.length > 0 && (
        <div className="intake-warnings">
          <ul>{response.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
        </div>
      )}
    </div>
  );
}

export function DishForm({ basketId, asOf, language, onPlanned, disabled = false }: DishFormProps) {
  const [dish, setDish] = useState("");
  const [servings, setServings] = useState("");
  const [needDate, setNeedDate] = useState("");
  const [diets, setDiets] = useState<DietKey[]>([]);
  const [tried, setTried] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DishResponse | null>(null);
  const id = useId();
  const fields = { dish: useRef<HTMLInputElement>(null), servings: useRef<HTMLInputElement>(null), needDate: useRef<HTMLInputElement>(null) };
  const minDate = dateOf(asOf);
  const values = { dish, servings, needDate, diets };
  const problems = tried ? dishProblems(values, minDate) : {}; // shown from the first Send on, then live

  const toggle = (key: DietKey) => setDiets((on) => (on.includes(key) ? on.filter((k) => k !== key) : [...on, key]));

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (busy || disabled) return;
    setTried(true);
    const found = dishProblems(values, minDate);
    const first = (["dish", "servings", "needDate"] as const).find((f) => found[f]);
    if (first) {
      fields[first].current?.focus();
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    let response: DishResponse;
    try {
      response = await planDish(buildDishRequest(values, language, basketId));
    } catch (err) {
      if (!(err instanceof IntakeError)) console.error(err);
      setError(errorText(err));
      return;
    } finally {
      setBusy(false);
    }
    setResult(response);
    if (response.dish) {
      // The dish is in the basket: clear its name and servings so a second Send cannot add it twice by accident.
      // The date and the diet chips stay for the next dish. With no dish, the fields stay for a fix.
      setDish("");
      setServings("");
      setTried(false);
    }
    onPlanned(response); // outside the try: a failing page callback is not a planning error
  };

  const invalid = (field: DishField) =>
    problems[field] ? { "aria-invalid": true, "aria-describedby": `${id}-${field}-error` } : {};
  const fieldError = (field: DishField) =>
    problems[field] && <p id={`${id}-${field}-error`} className="intake-field-error">{problems[field]}</p>;

  return (
    <section className="card intake intake-dish" aria-labelledby={`${id}-heading`}>
      <h2 id={`${id}-heading`}>Dish to basket</h2>
      <p>Name a dish and how many it serves. The gateway has it broken down into ingredients and adds each one to the
        basket, priced.</p>
      <form className="intake-form" noValidate aria-busy={busy} onSubmit={(e) => void submit(e)}>
        <div className="intake-field intake-wide">
          <label htmlFor={`${id}-dish`}>Dish</label>
          <input id={`${id}-dish`} ref={fields.dish} type="text" value={dish} maxLength={MAX_DISH_CHARS} required
                 autoComplete="off" placeholder="mansikkakakku" onChange={(e) => setDish(e.target.value)} {...invalid("dish")} />
          {fieldError("dish")}
        </div>
        <div className="intake-field">
          <label htmlFor={`${id}-servings`}>Servings</label>
          <input id={`${id}-servings`} ref={fields.servings} type="number" inputMode="numeric" min={1} max={MAX_SERVINGS}
                 step={1} required value={servings} placeholder="40" onChange={(e) => setServings(e.target.value)}
                 {...invalid("servings")} />
          {fieldError("servings")}
        </div>
        <div className="intake-field">
          <label htmlFor={`${id}-date`}>Delivery date</label>
          <input id={`${id}-date`} ref={fields.needDate} type="date" min={minDate || undefined} required value={needDate}
                 onChange={(e) => setNeedDate(e.target.value)} {...invalid("needDate")} />
          {fieldError("needDate")}
        </div>
        <fieldset className="intake-diets intake-wide" aria-describedby={`${id}-diet-help`}>
          <legend>Diet</legend>
          <div className="intake-chips">
            {DIETS.map((d) => (
              <button key={d.key} type="button" className="intake-diet" aria-pressed={diets.includes(d.key)}
                      onClick={() => toggle(d.key)}>
                {d.label}
              </button>
            ))}
          </div>
          <p id={`${id}-diet-help`} className="intake-help">
            Lactose-free food may still contain milk protein. For a milk allergy, choose Milk-free.
          </p>
        </fieldset>
        <div className="intake-actions intake-wide">
          {/* aria-disabled, not disabled, while planning: a disabled button would drop keyboard focus */}
          <button type="submit" className="primary intake-cta" disabled={disabled} aria-disabled={busy || undefined}>
            {busy ? "Planning…" : "Add the dish to the basket"}
          </button>
        </div>
        <p className={`intake-status intake-wide${busy ? " intake-spin" : ""}`} role="status">
          {busy ? "Planning the dish. This can take up to a minute…" : result?.dish ? result.message_for_user.en : ""}
        </p>
        {error && <p className="error intake-error intake-wide" role="alert">{error}</p>}
      </form>
      {result && (result.dish ? <DishHeader dish={result.dish} /> : <NoDish response={result} />)}
    </section>
  );
}
