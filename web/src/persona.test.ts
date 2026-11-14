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
