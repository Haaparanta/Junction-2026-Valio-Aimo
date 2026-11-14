/**
 * One popover for every clickable field (docs/basket-plan.md M24.1): a real <button> opens a non-modal panel.
 * Built on the browser's popover attribute, so the panel sits in the top layer (no clipping, no z-index fights)
 * and closes on Escape and on an outside click by itself. Focus moves into the panel when it opens and back to the
 * trigger when it closes. Under 600 px the panel is a bottom drawer (styles.css). No dependency.
 */
import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";

type Props = {
  /** The trigger's visible content. */
  label: ReactNode;
  /** The panel's heading, which also names the dialog. */
  title: string;
  triggerClass?: string;
  /** When the visible label alone does not say what the button does. It must contain the visible text. */
  triggerLabel?: string;
  disabled?: boolean;
  /** Rendered only while the panel is open; `close` hides it and returns focus to the trigger. */
  children: (close: () => void) => ReactNode;
};

const GAP = 6;
const EDGE = 16;
const wide = () => typeof window.matchMedia !== "function" || window.matchMedia("(min-width: 600px)").matches;

type PopoverEl = HTMLDivElement & { showPopover?: () => void; hidePopover?: () => void };

export function Popover({ label, title, triggerClass, triggerLabel, disabled, children }: Props) {
  const [open, setOpen] = useState(false);
  const id = `pop-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<PopoverEl>(null);

  /** Below the trigger (above it when there is no room), inside the viewport; a drawer leaves it to CSS. */
  const place = useCallback(() => {
    const p = panel.current;
    const t = trigger.current;
    if (!p || !t) return;
    if (!wide()) {
      p.style.top = "";
      p.style.left = "";
      return;
    }
    const r = t.getBoundingClientRect();
    const vw = document.documentElement.clientWidth;
    const vh = window.innerHeight;
    const w = p.offsetWidth || Math.min(384, vw - 2 * EDGE);
    const h = p.offsetHeight;
    const left = Math.max(EDGE, Math.min(r.left, vw - w - EDGE));
    const below = r.bottom + GAP + h <= vh || r.top - GAP - h < 0;
    const top = below ? r.bottom + GAP : r.top - GAP - h;
    p.style.left = `${left + window.scrollX}px`; // absolute in the top layer: document coordinates
    p.style.top = `${top + window.scrollY}px`;
  }, []);

  useEffect(() => {
    const p = panel.current;
    if (!p) return;
    const onBefore = (e: Event) => {
      if ((e as ToggleEvent).newState === "open") {
        setOpen(true);
        place();
      }
    };
    const onToggle = (e: Event) => {
      if ((e as ToggleEvent).newState === "open") {
        place();
        p.focus({ preventScroll: true });
        return;
      }
      setOpen(false);
      // Escape, the close button or a click on nothing focusable: back to the trigger. A click on another
      // control keeps the focus there.
      const a = document.activeElement;
      if (!a || a === document.body || p.contains(a)) trigger.current?.focus({ preventScroll: true });
    };
    // Tabbing out of the panel closes it, so it never covers the controls that come next.
    const onFocusOut = (e: FocusEvent) => {
      const to = e.relatedTarget as Node | null;
      if (to && !p.contains(to) && to !== trigger.current) {
        try {
          p.hidePopover?.();
        } catch {
          /* already hidden */
        }
      }
    };
    p.addEventListener("beforetoggle", onBefore);
    p.addEventListener("toggle", onToggle);
    p.addEventListener("focusout", onFocusOut);
    return () => {
      p.removeEventListener("beforetoggle", onBefore);
      p.removeEventListener("toggle", onToggle);
      p.removeEventListener("focusout", onFocusOut);
    };
  }, [place]);

  useEffect(() => {
    if (!open) return;
    const again = () => place();
    window.addEventListener("resize", again);
    const ro = typeof ResizeObserver === "function" && panel.current ? new ResizeObserver(again) : null;
    if (ro && panel.current) ro.observe(panel.current); // content that loads later changes the height
    return () => {
      window.removeEventListener("resize", again);
      ro?.disconnect();
    };
  }, [open, place]);

  const close = useCallback(() => {
    try {
      panel.current?.hidePopover?.();
    } catch {
      /* already hidden */
    }
  }, []);

  return (
    <>
      <button type="button" ref={trigger} className={triggerClass} aria-label={triggerLabel} disabled={disabled}
              popoverTarget={id} aria-haspopup="dialog" aria-expanded={open} aria-controls={id}>
        {label}
      </button>
      <div id={id} ref={panel} popover="auto" className="pop-panel" role="dialog" aria-modal="false"
           aria-labelledby={`${id}-title`} tabIndex={-1}>
        <div className="pop-head">
          <strong id={`${id}-title`}>{title}</strong>
          <button type="button" className="icon pop-close" aria-label="Close" onClick={close}>×</button>
        </div>
        {open && <div className="pop-body">{children(close)}</div>}
      </div>
    </>
  );
}
