import { afterEach, describe, expect, it, vi } from "vitest";
import { HIGHLIGHT_ATTR, HIGHLIGHT_MS, highlightElement, prefersReducedMotion, showBasketLine } from "./highlight";

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

const row = (id = "basket-line-3") => {
  const el = document.createElement("tr");
  el.id = id;
  el.tabIndex = -1;
  const table = document.createElement("table");
  const body = document.createElement("tbody");
  body.append(el);
  table.append(body);
  document.body.append(table);
  return el;
};

describe("highlighting a basket line", () => {
  it("scrolls smoothly, focuses and marks the row, then clears the mark", () => {
    vi.useFakeTimers();
    const el = row();
    const scroll = vi.fn();
    el.scrollIntoView = scroll;
    highlightElement(el, false);
    expect(scroll).toHaveBeenCalledWith({ behavior: "smooth", block: "center" });
    expect(document.activeElement).toBe(el);
    expect(el.getAttribute(HIGHLIGHT_ATTR)).toBe("fade");
    vi.advanceTimersByTime(HIGHLIGHT_MS);
    expect(el.hasAttribute(HIGHLIGHT_ATTR)).toBe(false);
  });

  it("jumps and keeps the colour still with reduced motion", () => {
    vi.useFakeTimers();
    const el = row();
    const scroll = vi.fn();
    el.scrollIntoView = scroll;
    highlightElement(el, true);
    expect(scroll).toHaveBeenCalledWith({ behavior: "auto", block: "center" });
    expect(el.getAttribute(HIGHLIGHT_ATTR)).toBe("still");
  });

  it("a second click restarts the mark instead of ending early", () => {
    vi.useFakeTimers();
    const el = row();
    highlightElement(el, false);
    vi.advanceTimersByTime(HIGHLIGHT_MS - 100);
    highlightElement(el, false);
    vi.advanceTimersByTime(200);
    expect(el.hasAttribute(HIGHLIGHT_ATTR)).toBe(true);
    vi.advanceTimersByTime(HIGHLIGHT_MS);
    expect(el.hasAttribute(HIGHLIGHT_ATTR)).toBe(false);
  });

  it("reads prefers-reduced-motion, and is false without matchMedia", () => {
    expect(prefersReducedMotion({ matchMedia: () => ({ matches: true }) as MediaQueryList })).toBe(true);
    expect(prefersReducedMotion({ matchMedia: () => ({ matches: false }) as MediaQueryList })).toBe(false);
    expect(prefersReducedMotion({} as Window)).toBe(false);
  });
});

describe("showing a basket line by id", () => {
  it("waits for a row that renders a few frames later", async () => {
    const frames: (() => void)[] = [];
    const shown = showBasketLine(3, { frame: (cb) => frames.push(cb), reduced: true });
    frames.shift()?.();
    const el = row();
    frames.shift()?.();
    await expect(shown).resolves.toBe(true);
    expect(el.getAttribute(HIGHLIGHT_ATTR)).toBe("still");
  });

  it("gives up and calls onMissing when the row never comes", async () => {
    const onMissing = vi.fn();
    const frame = (cb: () => void) => cb();
    await expect(showBasketLine(9, { frame, onMissing, reduced: true })).resolves.toBe(false);
    expect(onMissing).toHaveBeenCalledOnce();
  });
});
