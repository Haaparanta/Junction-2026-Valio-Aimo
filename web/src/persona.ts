/** One source for the persona's name and copy. Same agent, same tools, same limits: only the skin changes. */
import type { Persona } from "./voice/store";

export const PERSONAS: Record<Persona, { name: string; short: string; kind: string; icon: string; color: string }> = {
  aino: { name: "Aino", short: "Aino", kind: "AI ordering assistant", icon: "/favicon.svg", color: "#ffd23f" },
  cow: { name: "Mansikki", short: "Mansikki 🐄", kind: "AI ordering cow", icon: "/favicon-cow.svg", color: "#ff8fb4" },
};

/** Tab icon, title and theme colour follow the persona. */
export function applyPersonaChrome(p: Persona, doc: Document = document): void {
  const { name, icon, color } = PERSONAS[p];
  doc.title = `${name} · Valio Aimo ordering assistant`;
  const link = doc.querySelector<HTMLLinkElement>('link[rel="icon"]');
  if (link) link.href = icon;
  doc.querySelector<HTMLMetaElement>('meta[name="theme-color"]')?.setAttribute("content", color);
}

export const personaName = (p: Persona) => PERSONAS[p].name;

/** Silent note for the agent when the buyer switches persona mid-call. */
export const personaNote = (p: Persona) =>
  p === "cow"
    ? "The buyer switched the on-screen persona to Mansikki, a cow whose voice is replaced by moos. From now on your name is Mansikki. Nothing else changes."
    : "The buyer switched the on-screen persona back to Aino. From now on your name is Aino. Nothing else changes.";
