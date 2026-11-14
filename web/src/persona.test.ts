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
