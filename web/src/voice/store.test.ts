import { describe, expect, it } from "vitest";
import { basket } from "../testing/fixtures";
import { newJob } from "./dishJobs";
import {
  createStore, dismissJob, focusBasket, initialUi, intakeOf, jobsForBasket, markAnnounced, optionsFor, putJob, quoteLoaded,
  receiveBasket, receiveImport, showQuote, showToast, toastActionOf,
  type Ui,
} from "./store";

const state = (over: Partial<Ui> = {}): Ui => ({ ...initialUi, ...over });
const apply = (s: Ui, patch: Partial<Ui>): Ui => ({ ...s, ...patch });

describe("focusBasket", () => {
  it("a new basket drops the quote, confirmation and order of another basket", () => {
    const s = state({
      basketId: "B-AAAAAAAAAA", quoteId: "Q-OLD", quoteBasketId: "B-AAAAAAAAAA", confirmQuoteId: "Q-OLD",
      order: { quoteId: "Q-OLD", orderId: "O-1", status: "completed", message: { fi: "", en: "" } },
      replaceLine: { basketId: "B-AAAAAAAAAA", lineId: 2 },
    });
    const next = apply(s, focusBasket(s, "B-0A1B2C3D4E"));
    expect(next).toMatchObject({
      basketId: "B-0A1B2C3D4E", quoteId: null, confirmQuoteId: null, order: null, replaceLine: null, basket: null,
    });
  });
  it("keeps a quote that was made for the basket coming into focus", () => {
    const s = state({ basketId: null, quoteId: "Q-1", quoteBasketId: "B-0A1B2C3D4E", confirmQuoteId: "Q-1" });
    expect(apply(s, focusBasket(s, "B-0A1B2C3D4E"))).toMatchObject({ quoteId: "Q-1", confirmQuoteId: "Q-1" });
  });
  it("drops a single-offer quote when a basket comes into focus", () => {
    const s = state({ quoteId: "Q-SINGLE", quoteBasketId: null });
    expect(apply(s, focusBasket(s, "B-0A1B2C3D4E")).quoteId).toBeNull();
  });
  it("the same basket again changes nothing, and an approval always stays", () => {
    const s = state({ basketId: "B-0A1B2C3D4E", quoteId: "Q-1", approvalId: "A-1" });
    expect(focusBasket(s, "B-0A1B2C3D4E")).toEqual({});
    expect(apply(s, focusBasket(s, null))).toMatchObject({ basketId: null, quoteId: null, approvalId: "A-1" });
  });
  it("keeps the newest version of the basket", () => {
    const s = state({ basketId: "B-0A1B2C3D4E", basket: basket({ version: 5 }) });
    expect(focusBasket(s, "B-0A1B2C3D4E", basket({ version: 4 }))).toEqual({});
    expect(focusBasket(s, "B-0A1B2C3D4E", basket({ version: 6 })).basket?.version).toBe(6);
  });
  it("stores the answer when it starts a basket", () => {
    const s = state();
    expect(apply(s, focusBasket(s, "B-0A1B2C3D4E", basket())).basket?.basket_id).toBe("B-0A1B2C3D4E");
  });
});

describe("receiveBasket", () => {
  it("takes answers for the basket in focus only", () => {
    const s = state({ basketId: "B-AAAAAAAAAA" });
    expect(receiveBasket(s, basket())).toEqual({});
    const t = state({ basketId: "B-0A1B2C3D4E" });
    expect(receiveBasket(t, basket()).basket?.basket_id).toBe("B-0A1B2C3D4E");
  });
});

describe("quotes on screen", () => {
  it("guesses the basket in focus, then corrects it from the loaded quote", () => {
    let s = state({ basketId: "B-0A1B2C3D4E" });
    s = apply(s, showQuote(s, "Q-1"));
    expect(s).toMatchObject({ quoteId: "Q-1", quoteBasketId: "B-0A1B2C3D4E" });
    s = apply(s, quoteLoaded(s, { quote_id: "Q-1", basket_id: null }));
    expect(s.quoteBasketId).toBeNull();
  });
  it("brings the quote's basket into focus when none is", () => {
    let s = state();
    s = apply(s, showQuote(s, "Q-1"));
    s = apply(s, quoteLoaded(s, { quote_id: "Q-1", basket_id: "B-0A1B2C3D4E" }));
    expect(s).toMatchObject({ basketId: "B-0A1B2C3D4E", quoteId: "Q-1", quoteBasketId: "B-0A1B2C3D4E" });
  });
  it("ignores a quote that is no longer on screen", () => {
    const s = state({ quoteId: "Q-2" });
    expect(quoteLoaded(s, { quote_id: "Q-1", basket_id: "B-0A1B2C3D4E" })).toEqual({});
  });
  it("a new quote clears the previous quote's order", () => {
    const s = state({ quoteId: "Q-1", order: { quoteId: "Q-1", orderId: "O-1", status: "completed", message: { fi: "", en: "" } } });
    expect(apply(s, showQuote(s, "Q-2", "B-0A1B2C3D4E"))).toMatchObject({ quoteId: "Q-2", order: null });
  });
});

describe("optionsFor (show_products with a line_id)", () => {
  it("replaces a line only of the basket in focus, with a valid line id", () => {
    const s = state({ basketId: "B-0A1B2C3D4E" });
    expect(optionsFor(s, "OS-1", 2).replaceLine).toEqual({ basketId: "B-0A1B2C3D4E", lineId: 2 });
    expect(optionsFor(s, "OS-1", undefined).replaceLine).toBeNull();
    expect(optionsFor(s, "OS-1", 0).replaceLine).toBeNull();
    expect(optionsFor(s, "OS-1", "2").replaceLine).toBeNull();
    expect(optionsFor(s, "OS-1", 2.5).replaceLine).toBeNull();
    expect(optionsFor(state(), "OS-1", 2).replaceLine).toBeNull();
  });
});

describe("toast with an action", () => {
  it("shows the action only with the text it came with", () => {
    const run = () => undefined;
    let s = apply(state(), showToast("Removed line 2.", { label: "Undo", run }));
    expect(toastActionOf(s)?.label).toBe("Undo");
    s = apply(s, { toast: "Aino ended the call." }); // another toast replaces the text
    expect(toastActionOf(s)).toBeNull();
    expect(toastActionOf(apply(s, showToast("Saved.")))).toBeNull();
  });
  it("the store applies function patches against the latest state", () => {
    const st = createStore(state());
    st.set((s) => focusBasket(s, "B-0A1B2C3D4E", basket()));
    st.set((s) => receiveBasket(s, basket({ version: 2 })));
    expect(st.get().basket?.version).toBe(2);
  });
});

describe("receiveImport", () => {
  const answer = (rows: number, basketId = "B-0A1B2C3D4E") => ({
    status: "ok", reason_code: null, message_for_user: { fi: "", en: "" }, warnings: [], basket_id: basketId,
    basket: basket({ basket_id: basketId }), counts: {}, extraction: null,
    rows: Array.from({ length: rows }, (_, i) => ({
      row_number: i + 2, status: "priced" as const, message: { fi: "", en: "" }, line_id: i + 1, raw_text: "x",
    })),
  });

  it("puts the import's basket in focus with the gateway's answer and keeps the summary for it", () => {
    const r = answer(2);
    const s = state({ ...receiveImport(state(), "sheet", r) });
    expect(s.basketId).toBe("B-0A1B2C3D4E");
    expect(s.basket).toBe(r.basket);
    expect(intakeOf(s)).toEqual({ basketId: "B-0A1B2C3D4E", kind: "sheet", response: r });
    expect(intakeOf({ ...s, basketId: "B-FFFFFFFFFF" })).toBeNull(); // another basket in focus: no summary
  });

  it("leaves the screen alone when a photo gave no rows and no basket was in focus", () => {
    expect(receiveImport(state(), "photo", answer(0))).toEqual({});
    const inFocus = state({ basketId: "B-0A1B2C3D4E" });
    expect(receiveImport(inFocus, "photo", answer(0)).intake?.kind).toBe("photo");
  });
});

describe("dish jobs in the store", () => {
  const job = (id: string, phase: "running" | "polling" | "done" | "failed", basketId = "B-0A1B2C3D4E") =>
    ({ ...newJob(id, basketId, "running", 0), phase });

  it("keeps a job's announced mark across updates, and dismisses it", () => {
    let s = state({ ...putJob(state(), job("DJ-1", "running")) });
    s = state({ ...s, ...markAnnounced(s, "DJ-1") });
    s = state({ ...s, ...putJob(s, job("DJ-1", "done")) });
    expect(s.dishJobs["DJ-1"]).toMatchObject({ phase: "done", announced: true });
    expect(markAnnounced(s, "DJ-1")).toEqual({});
    expect(dismissJob(s, "DJ-1")).toEqual({ dishJobs: {} });
    expect(dismissJob(s, "DJ-9")).toEqual({});
  });

  it("the basket card plans while the basket lists an unfinished job or one of its jobs runs", () => {
    const b = basket({ dish_jobs: ["DJ-1"] });
    expect(jobsForBasket({}, b).planning).toBe(true); // listed, not started yet
    expect(jobsForBasket({ "DJ-1": job("DJ-1", "polling") }, b).planning).toBe(true);
    expect(jobsForBasket({ "DJ-1": job("DJ-1", "done") }, b).planning).toBe(false); // the basket is about to refresh
    const none = basket({ dish_jobs: [] });
    expect(jobsForBasket({ "DJ-2": job("DJ-2", "running") }, none).planning).toBe(true);
    expect(jobsForBasket({ "DJ-2": job("DJ-2", "running", "B-FFFFFFFFFF") }, none).planning).toBe(false);
    const failed = jobsForBasket({ "DJ-3": { ...job("DJ-3", "failed"), message: "AI unavailable." } }, none);
    expect(failed.notices).toEqual([{ jobId: "DJ-3", text: "AI unavailable." }]);
    expect(jobsForBasket({}, null)).toEqual({ planning: false, notices: [] });
  });
});
