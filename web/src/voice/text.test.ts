import { describe, expect, it } from "vitest";
import { initialUi, upsertTurn } from "./store";
import { endsWithQuestion, stripTags } from "./text";

describe("captions", () => {
  it("strips audio tags, including punctuated ones", () => {
    expect(stripTags("[laughs] Hei! [half-laughing] Tilataanko?")).toBe("Hei! Tilataanko?");
    expect(stripTags("Selvä [sighs], tilaan.")).toBe("Selvä, tilaan.");
  });
  it("detects a question at the end", () => {
    expect(endsWithQuestion("Sopiiko maitojuoma? [curious]")).toBe(true);
    expect(endsWithQuestion("Tilaus on lähetetty.")).toBe(false);
  });
  it("keeps the last turns and updates in place", () => {
    let turns = initialUi.turns;
    for (let i = 0; i < 12; i++) turns = upsertTurn(turns, `t${i}`, "agent", (t) => ({ ...t, text: `${i}` }));
    expect(turns).toHaveLength(8);
    turns = upsertTurn(turns, "t11", "agent", (t) => ({ ...t, text: t.text + "!" }));
    expect(turns.at(-1)?.text).toBe("11!");
  });
});
