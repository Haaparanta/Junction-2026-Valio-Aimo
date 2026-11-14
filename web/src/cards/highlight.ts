/**
 * Show one basket line (docs/basket-plan.md M24.8, M25.5): a quote line and an import summary row both scroll to
 * the basket line, focus it and highlight it briefly. With prefers-reduced-motion the page jumps instead of
 * scrolling smoothly, and the highlight is a steady colour (styles.css turns its fade off).
 *
 * The highlight is a data attribute, not a class: React owns the row's className and would drop a class it did not
 * set on the next render.
 */
import { lineDomId } from "./basket";

export const HIGHLIGHT_ATTR = "data-flash";
export const HIGHLIGHT_MS = 1800;
/** How many animation frames to wait for a row that is still rendering (about 1.5 s). */
export const WAIT_FRAMES = 90;

export const prefersReducedMotion = (win: Pick<Window, "matchMedia"> | undefined = globalThis.window): boolean =>
  !!win && typeof win.matchMedia === "function" && win.matchMedia("(prefers-reduced-motion: reduce)").matches;

const timers = new WeakMap<Element, ReturnType<typeof setTimeout>>();

/** Scroll an element into view, focus it and mark it for HIGHLIGHT_MS; a second call restarts the mark. */
export function highlightElement(el: HTMLElement, reduced: boolean, ms = HIGHLIGHT_MS): void {
  el.scrollIntoView?.({ behavior: reduced ? "auto" : "smooth", block: "center" });
  el.focus({ preventScroll: true });
  const previous = timers.get(el);
  if (previous) clearTimeout(previous);
  el.removeAttribute(HIGHLIGHT_ATTR);
  void el.offsetWidth; // restart the CSS fade
  el.setAttribute(HIGHLIGHT_ATTR, reduced ? "still" : "fade");
  timers.set(el, setTimeout(() => {
    el.removeAttribute(HIGHLIGHT_ATTR);
    timers.delete(el);
  }, ms));
}

export type ShowLineOptions = {
  /** Called when the row never appeared, for example because the line was removed. */
  onMissing?: () => void;
  doc?: Pick<Document, "getElementById">;
  frame?: (cb: () => void) => void;
  reduced?: boolean;
};

/**
 * Show basket line `lineId`: waits a few frames for its row (the basket card may be fetching), then highlights it.
 * Resolves to true when the row was shown.
 */
export function showBasketLine(lineId: number, opts: ShowLineOptions = {}): Promise<boolean> {
  const doc = opts.doc ?? (typeof document === "undefined" ? null : document);
  const frame = opts.frame ?? (typeof requestAnimationFrame === "function" ? (cb: () => void) => void requestAnimationFrame(cb) : null);
  const id = lineDomId(lineId);
  return new Promise((resolve) => {
    const attempt = (left: number) => {
      const el = doc?.getElementById(id) ?? null;
      if (el instanceof HTMLElement) {
        highlightElement(el, opts.reduced ?? prefersReducedMotion());
        resolve(true);
        return;
      }
      if (left > 0 && frame) {
        frame(() => attempt(left - 1));
        return;
      }
      opts.onMissing?.();
      resolve(false);
    };
    attempt(WAIT_FRAMES);
  });
}
