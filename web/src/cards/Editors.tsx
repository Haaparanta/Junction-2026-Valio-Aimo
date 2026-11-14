/**
 * Inline editors for a basket line (M24.2, M24.3). They send the buyer's input to the gateway and show its answer:
 * the units needed, the overshoot, the order-by time or the cut-off message all come from the response.
 */
import { useEffect, useId, useRef, useState } from "react";
import type { BasketLine, Unit } from "../api";
import { formatAmount, isIsoDate, parseAmount, stepAmount, type LineChange } from "./basket";

/** Sends one change; resolves to the error to show, or null when the gateway took it. */
export type PatchFn = (change: LineChange) => Promise<string | null>;

const UNITS: Unit[] = ["L", "KG", "PCS"];

/** −/+ and a number field (a decimal comma is fine), the unit next to it; commits on Enter, blur or −/+. */
export function QtyEditor({ l, onPatch }: { l: BasketLine; onPatch: PatchFn }) {
  const [draft, setDraft] = useState(formatAmount(l.amount));
  const [unit, setUnit] = useState<"" | Unit>(l.unit ?? "");
  const [pending, setPending] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const busy = useRef(false);
  const latest = useRef(l);
  const group = useRef<HTMLDivElement>(null);
  const errId = useId();
  // Every gateway answer is a new line object: show what it says (the typed draft only lives until then).
  useEffect(() => {
    latest.current = l;
    if (busy.current) return;
    setDraft(formatAmount(l.amount));
    setUnit(l.unit ?? "");
  }, [l]);

  const needsUnit = l.unit === null; // a photo or sheet row whose unit could not be read (needs_amount)
  const commit = async (amount: number | null) => {
    if (busy.current) return;
    if (amount === null) {
      setErr("Type an amount above 0, for example 2,5.");
      return;
    }
    if (needsUnit && unit === "") {
      setErr("Choose a unit too.");
      return;
    }
    if (amount === l.amount && !needsUnit) {
      setErr(null);
      setDraft(formatAmount(l.amount));
      return;
    }
    busy.current = true;
    setPending(true);
    setErr(null);
    setDraft(formatAmount(amount));
    const e = await onPatch({ amount, unit: needsUnit ? unit : "" });
    busy.current = false;
    setPending(false);
    if (e) {
      setErr(e); // keep the typed amount, so Enter tries again
      return;
    }
    setDraft(formatAmount(latest.current.amount)); // the gateway's answer
    setUnit(latest.current.unit ?? "");
  };

  const base = parseAmount(draft) ?? l.amount;
  const less = stepAmount(base, -1);
  const more = stepAmount(base, 1);
  const leaveGroup = (to: EventTarget | null) => {
    if (group.current?.contains(to as Node)) return; // moving to −/+ or the unit: those commit themselves
    if (draft.trim() === "") {
      setDraft(formatAmount(l.amount));
      setErr(null);
      return;
    }
    if (draft.trim() !== formatAmount(l.amount) || (needsUnit && unit !== "")) void commit(parseAmount(draft));
  };

  return (
    <div className="editor">
      <div className="qty-edit" role="group" aria-label={`Amount of line ${l.line_id}`} aria-busy={pending} ref={group}
           onBlur={(e) => leaveGroup(e.relatedTarget)}>
        <button type="button" className="step" aria-label={`Less, line ${l.line_id}`} disabled={pending || less === null}
                onClick={() => void commit(less)}>−</button>
        <input inputMode="decimal" autoComplete="off" value={draft} readOnly={pending} placeholder="Amount"
               aria-label={`Amount of line ${l.line_id}${l.unit ? `, in ${l.unit}` : ""}`} aria-invalid={err ? true : undefined}
               aria-describedby={err ? errId : undefined}
               onChange={(e) => {
                 setDraft(e.target.value);
                 setErr(null);
               }}
               onKeyDown={(e) => {
                 if (e.key === "Enter") {
                   e.preventDefault();
                   void commit(parseAmount(draft));
                 } else if (e.key === "Escape" && draft !== formatAmount(l.amount)) {
                   e.stopPropagation();
                   setDraft(formatAmount(l.amount));
                   setErr(null);
                 }
               }} />
        {needsUnit ? (
          <select aria-label={`Unit of line ${l.line_id}`} value={unit} disabled={pending}
                  onChange={(e) => setUnit(e.target.value as "" | Unit)}>
            <option value="">unit</option>
            {UNITS.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
        ) : (
          <span className="unit" aria-hidden="true">{l.unit}</span>
        )}
        <button type="button" className="step" aria-label={`More, line ${l.line_id}`} disabled={pending || more === null}
                onClick={() => void commit(more)}>+</button>
      </div>
      {pending && <small className="pending" role="status">Saving…</small>}
      {err && <small className="error" id={errId} role="alert">{err}</small>}
    </div>
  );
}

/** A date input; commits on Enter, blur, or a moment after a full date is picked. */
export function DateEditor({ l, onPatch }: { l: BasketLine; onPatch: PatchFn }) {
  const [draft, setDraft] = useState(l.need_date);
  const [pending, setPending] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const busy = useRef(false);
  const latest = useRef(l);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const errId = useId();
  useEffect(() => {
    latest.current = l;
    if (!busy.current) setDraft(l.need_date);
  }, [l]);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const commit = async (v: string) => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    if (busy.current || v === l.need_date) return;
    if (!isIsoDate(v)) {
      if (v === "") setDraft(l.need_date);
      else setErr("Pick a full date.");
      return;
    }
    busy.current = true;
    setPending(true);
    setErr(null);
    const e = await onPatch({ need_date: v });
    busy.current = false;
    setPending(false);
    if (e) setErr(e);
    else setDraft(latest.current.need_date); // the gateway's answer
  };

  return (
    <div className="editor">
      <input type="date" value={draft} readOnly={pending} aria-busy={pending}
             aria-label={`Delivery date of line ${l.line_id}`} aria-invalid={err ? true : undefined}
             aria-describedby={err ? errId : undefined}
             onChange={(e) => {
               const v = e.target.value;
               setDraft(v);
               setErr(null);
               if (timer.current) clearTimeout(timer.current);
               if (isIsoDate(v)) timer.current = setTimeout(() => void commit(v), 900); // picked, not half-typed
             }}
             onBlur={() => void commit(draft)}
             onKeyDown={(e) => {
               if (e.key === "Enter") {
                 e.preventDefault();
                 void commit(draft);
               }
             }} />
      {pending && <small className="pending" role="status">Saving…</small>}
      {err && <small className="error" id={errId} role="alert">{err}</small>}
    </div>
  );
}
