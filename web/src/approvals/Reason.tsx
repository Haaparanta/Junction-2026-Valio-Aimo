import { useId, useState } from "react";
import { parseReason } from "../cards/basket";

/**
 * One approval reason, "OVER_ORDER_CAP: EUR 1010.00 is above …": a button with the plain title that expands to the
 * gateway's detail and the code (M24.8). Enter or Space toggles it, Escape folds it again.
 */
export function Reason({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const id = `reason-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const r = parseReason(text);
  if (!r.code) return <>{text}</>;
  return (
    <>
      <button type="button" className="link reason-btn" aria-expanded={open} aria-controls={id}
              onClick={() => setOpen((o) => !o)}
              onKeyDown={(e) => {
                if (e.key === "Escape" && open) {
                  e.stopPropagation();
                  setOpen(false);
                }
              }}>
        {open ? "▾" : "▸"} {r.title}
      </button>
      <div id={id} className="reason-detail" hidden={!open}>
        {r.detail && <p>{r.detail}</p>}
        <p className="muted">Code <code>{r.code}</code></p>
      </div>
    </>
  );
}
