/** One source for the persona's name and copy. Same agent, same tools, same limits: only the skin changes. */
import type { Persona } from "./voice/store";

export const PERSONAS: Record<Persona, { name: string; short: string; kind: string }> = {
  aino: { name: "Aino", short: "Aino", kind: "AI ordering assistant" },
  cow: { name: "Mansikki", short: "Mansikki 🐄", kind: "AI ordering cow" },
};

export const personaName = (p: Persona) => PERSONAS[p].name;

/** Silent note for the agent when the buyer switches persona mid-call. */
export const personaNote = (p: Persona) =>
  p === "cow"
    ? "The buyer switched the on-screen persona to Mansikki, a cow whose voice is replaced by moos. From now on your name is Mansikki. Nothing else changes."
    : "The buyer switched the on-screen persona back to Aino. From now on your name is Aino. Nothing else changes.";
