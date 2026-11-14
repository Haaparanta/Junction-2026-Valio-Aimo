import { describe, expect, it } from "vitest";
import { personaName, personaNote } from "./persona";

describe("persona", () => {
  it("names the cow Mansikki and the default Aino", () => {
    expect(personaName("cow")).toBe("Mansikki");
    expect(personaName("aino")).toBe("Aino");
  });
  it("tells the agent its new name on a switch, and that nothing else changes", () => {
    expect(personaNote("cow")).toContain("your name is Mansikki");
    expect(personaNote("aino")).toContain("your name is Aino");
    expect(personaNote("cow")).toContain("Nothing else changes");
  });
});

import { choiceMessage } from "./cards/Cards";

describe("choosing an option by clicking", () => {
  const offer = {
    offer_id: "OS-60674F07:464306", tier: "best" as const, product_id: "464306", name_fi: "Valio Arki Eila 1 l",
    api_unit: "ST", qty: 1000, content_total: "1000", unit_price_net: "1.01", total_net: "1010.00",
    price_per_base_unit: "1.01", base_unit: "L", delivery_date: "2026-11-16", order_by: "2026-11-15T17:00:00+02:00",
    stock: "untracked", stock_qty: null, flags: [], explanation: { fi: "", en: "" },
  };
  it("sends the offer_id and no price", () => {
    const m = choiceMessage(offer);
    expect(m).toContain("offer_id OS-60674F07:464306");
    expect(m).toContain("the best option");
    expect(m).not.toMatch(/1010|€|EUR/);
  });
});

import { applyPersonaChrome } from "./persona";

describe("persona chrome", () => {
  it("swaps the tab icon, title and theme colour", () => {
    document.head.innerHTML = '<link rel="icon" href="/favicon.svg"><meta name="theme-color" content="#ffd23f">';
    applyPersonaChrome("cow");
    expect(document.title).toBe("Mansikki · Valio Aimo ordering assistant");
    expect(document.querySelector("link[rel=icon]")?.getAttribute("href")).toBe("/favicon-cow.svg");
    expect(document.querySelector("meta[name=theme-color]")?.getAttribute("content")).toBe("#ff8fb4");
    applyPersonaChrome("aino");
    expect(document.title).toBe("Aino · Valio Aimo ordering assistant");
  });
});
