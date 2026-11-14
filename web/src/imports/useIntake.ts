/**
 * What the page does after an intake on screen succeeded (docs/basket-plan.md M25.5, M27, M28): the basket it went
 * into comes into focus with the gateway's answer, the import summary shows under the basket card, and during a live
 * call the agent gets the matching silent note (built from gateway fields only, imports/notes.ts).
 */
import { useMemo } from "react";
import type { DishResponse, ImportResponse } from "../api";
import { hasBasket, focusSoon } from "../cards/actions";
import { focusBasket, receiveImport, ui } from "../voice/store";
import { useAgentNote } from "../voice/useAgentNote";
import { dishNote, importNote, photoNote } from "./notes";

export const IMPORT_SUMMARY_ID = "import-summary";

/** The control that was used may be gone (the empty state hides once a basket is in focus): move focus on. */
function focusIfLost(id: string): void {
  const a = typeof document === "undefined" ? null : document.activeElement;
  if (!a || a === document.body) focusSoon(id);
}

export type IntakeHandlers = {
  sheet: (r: ImportResponse) => void;
  photo: (r: ImportResponse) => void;
  dish: (r: DishResponse) => void;
};

export function useIntake(): IntakeHandlers {
  const notify = useAgentNote();
  return useMemo(() => {
    const list = (kind: "sheet" | "photo") => (r: ImportResponse) => {
      ui.set((s) => receiveImport(s, kind, r));
      notify(kind === "photo" ? photoNote(r) : importNote(r));
      if (ui.get().basketId === r.basket_id) requestAnimationFrame(() => focusIfLost(IMPORT_SUMMARY_ID));
    };
    return {
      sheet: list("sheet"),
      photo: list("photo"),
      dish: (r: DishResponse) => {
        // With no dish, nothing was added: a basket comes into focus only when one already was.
        if (hasBasket(r) && (r.dish || ui.get().basketId)) ui.set((s) => focusBasket(s, r.basket_id, r.basket));
        notify(dishNote(r));
        if (ui.get().basketId === r.basket_id) requestAnimationFrame(() => focusIfLost("basket-title"));
      },
    };
  }, [notify]);
}
