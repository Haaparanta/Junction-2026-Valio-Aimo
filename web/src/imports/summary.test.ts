import { describe, expect, it } from "vitest";
import { importResponse, item, line, row } from "./fixtures";
import { attentionFirst, confidenceFor, needsAttention, notAddedText, summaryText } from "./summary";

describe("the summary line, from the gateway's counts", () => {
  it("words the counts in English and Finnish, priced first", () => {
    expect(summaryText({ unmatched: 1, priced: 9, needs_choice: 2 })).toEqual({
      en: "12 rows: 9 priced, 2 need your choice, 1 not found",
      fi: "12 riviä: 9 hinnoiteltu, 2 odottaa valintaasi, 1 ei löytynyt",
    });
  });

  it("uses the singular for one row", () => {
    expect(summaryText({ needs_choice: 1 })).toEqual({ en: "1 row: 1 needs your choice", fi: "1 rivi: 1 odottaa valintaasi" });
    expect(summaryText({ priced: 3, needs_amount: 1, invalid: 1 }).en).toBe(
      "5 rows: 3 priced, 1 needs an amount, 1 could not be read",
    );
    expect(summaryText({ needs_amount: 2 }).en).toBe("2 rows: 2 need an amount");
  });

  it("covers every status in a fixed order and leaves out zero counts", () => {
    const t = summaryText({
      invalid: 1, cutoff_passed: 1, not_deliverable: 1, unmatched: 1, needs_amount: 1, needs_choice: 1, priced: 1, x: 0,
    });
    expect(t.en).toBe(
      "7 rows: 1 priced, 1 needs your choice, 1 needs an amount, 1 not found, 1 not deliverable, " +
        "1 past the order cut-off, 1 could not be read",
    );
    expect(t.fi).toBe(
      "7 riviä: 1 hinnoiteltu, 1 odottaa valintaasi, 1 määrä puuttuu, 1 ei löytynyt, 1 ei toimitettavissa, " +
        "1 tilausaika umpeutunut, 1 ei luettavissa",
    );
    expect(summaryText({ priced: 2, needs_choice: 0 }).en).toBe("2 rows: 2 priced");
  });

  it("says so when nothing was imported, as after an unreadable photo", () => {
    expect(summaryText({})).toEqual({ en: "No rows were imported", fi: "Yhtään riviä ei tuotu" });
    expect(summaryText({ priced: 0 }).en).toBe("No rows were imported");
  });

  it("keeps a status it does not know yet, by its code, after the known ones", () => {
    expect(summaryText({ priced: 1, on_hold: 2 }).en).toBe("3 rows: 1 priced, 2 on hold");
  });
});

describe("rows that need attention come first", () => {
  const rows = [
    row(2, "priced", 1),
    row(3, "needs_choice", 2),
    row(4, "priced", 3),
    row(5, "invalid", null),
    row(6, "unmatched", 4),
    row(7, "needs_amount", 5),
  ];

  it("puts every row that is not priced before the priced ones, keeping the gateway's order in each group", () => {
    expect(attentionFirst(rows).map((r) => r.row_number)).toEqual([3, 5, 6, 7, 2, 4]);
    expect(rows.map((r) => r.row_number)).toEqual([2, 3, 4, 5, 6, 7]); // the input is not changed
  });

  it("counts only priced rows as done", () => {
    expect(rows.filter(needsAttention).map((r) => r.status)).toEqual(["needs_choice", "invalid", "unmatched", "needs_amount"]);
    expect(attentionFirst([])).toEqual([]);
  });
});

describe("confidence chips for photo rows", () => {
  const extraction = {
    items: [item("maito 20 l", "high"), item("voi 5 kg", "medium"), item("servetit 500 kpl", "low")],
    handwritten: true,
    unreadable: [],
  };

  it("takes the extraction item at the row's place, or the item with the same text", () => {
    const r = importResponse([], {}, [], { extraction });
    expect(confidenceFor(row(1, "priced", 1, "maito 20 l"), r)).toBe("high");
    expect(confidenceFor(row(3, "unmatched", 3, "servetit 500 kpl"), r)).toBe("low");
    expect(confidenceFor(row(7, "priced", 2, "voi 5 kg"), r)).toBe("medium"); // another place, same text
  });

  it("falls back to the basket line, and has none for sheet rows", () => {
    const photo = importResponse([], {}, [line({ line_id: 9, confidence: "low" })], { extraction });
    expect(confidenceFor(row(9, "needs_amount", 9, "kerma ?"), photo)).toBe("low");
    expect(confidenceFor(row(9, "invalid", null, "kerma ?"), photo)).toBeNull();
    const sheet = importResponse([], {}, [line({ line_id: 1 })]);
    expect(confidenceFor(row(2, "priced", 1, "voi;5;kg"), sheet)).toBeNull();
  });

  it("says why a row has no line", () => {
    expect(notAddedText(false)).toMatch(/fix the row in the file/);
    expect(notAddedText(true)).toMatch(/clearer photo/);
  });
});
