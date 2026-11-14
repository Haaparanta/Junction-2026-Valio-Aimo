import { afterEach, describe, expect, it, vi } from "vitest";
import { api, errorDetail, HttpError } from "./api";

type Sent = { url: string; method: string; body: unknown };

/** Replace fetch with one canned answer and record what was sent. */
function fakeFetch(status: number, body: unknown): Sent[] {
  const sent: Sent[] = [];
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    sent.push({ url, method: init.method ?? "GET", body: init.body ? JSON.parse(String(init.body)) : undefined });
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  });
  return sent;
}

afterEach(() => vi.unstubAllGlobals());

describe("errorDetail", () => {
  it("prefers the gateway's message, then FastAPI's detail", () => {
    expect(errorDetail({ message_for_user: { fi: "Ei", en: "Basket is ordered." } }, "x")).toBe("Basket is ordered.");
    expect(errorDetail({ detail: "basket not found" }, "x")).toBe("basket not found");
    expect(errorDetail({ detail: [{ msg: "Input should be a valid date" }] }, "x")).toBe("Input should be a valid date");
    expect(errorDetail(null, "Not Found")).toBe("Not Found");
  });
});

describe("basket calls", () => {
  it("GET /v1/baskets/current: a 404 means no basket, not an error", async () => {
    fakeFetch(404, { detail: "basket not found" });
    await expect(api.currentBasket()).resolves.toBeNull();
  });
  it("other failures still throw, with the body kept for its reason_code", async () => {
    fakeFetch(409, { reason_code: "basket_locked", message_for_user: { fi: "", en: "Already ordered." } });
    const e = await api.basket("B-0A1B2C3D4E").catch((x: unknown) => x);
    expect(e).toBeInstanceOf(HttpError);
    expect((e as HttpError).message).toBe("Already ordered.");
    expect((e as HttpError).body).toMatchObject({ reason_code: "basket_locked" });
  });
  it("PATCH sends all four fields to the line's path", async () => {
    const sent = fakeFetch(200, {});
    await api.patchLine("B-0A1B2C3D4E", 2, { amount: 20, unit: "", need_date: "", offer_id: "" });
    expect(sent[0]).toEqual({
      url: "/v1/baskets/B-0A1B2C3D4E/lines/2", method: "PATCH",
      body: { amount: 20, unit: "", need_date: "", offer_id: "" },
    });
  });
  it("from-offer starts a new basket without one in focus, and replaces only with a real line id", async () => {
    const sent = fakeFetch(200, {});
    await api.addFromOffer(null, "OS-60674F07:464306");
    await api.addFromOffer("B-0A1B2C3D4E", "OS-60674F07:464306", 3);
    await api.addFromOffer("B-0A1B2C3D4E", "OS-60674F07:464306", 2.5);
    expect(sent.map((s) => s.url)).toEqual([
      "/v1/baskets/new/lines/from-offer", "/v1/baskets/B-0A1B2C3D4E/lines/from-offer",
      "/v1/baskets/B-0A1B2C3D4E/lines/from-offer",
    ]);
    expect(sent.map((s) => (s.body as { replace_line_id: number }).replace_line_id)).toEqual([0, 3, 0]);
  });
  it("remove, restore, quote and order use the documented routes", async () => {
    const sent = fakeFetch(200, {});
    await api.removeLine("B-0A1B2C3D4E", 3);
    await api.restoreLine("B-0A1B2C3D4E", 3);
    await api.quoteBasket("B-0A1B2C3D4E");
    await api.placeOrder("Q-1A2B3C4D5E");
    await api.product("464306");
    expect(sent.map((s) => `${s.method} ${s.url}`)).toEqual([
      "DELETE /v1/baskets/B-0A1B2C3D4E/lines/3", "POST /v1/baskets/B-0A1B2C3D4E/lines/3/restore",
      "POST /v1/baskets/quote", "POST /v1/orders", "GET /v1/products/464306",
    ]);
    expect(sent[2]?.body).toEqual({ basket_id: "B-0A1B2C3D4E" });
    expect(sent[3]?.body).toEqual({ quote_id: "Q-1A2B3C4D5E" });
  });
  it("ids are path-encoded, and a bad line id never builds another path", async () => {
    const sent = fakeFetch(200, {});
    await api.removeLine("B-1/../x", Number.NaN);
    expect(sent[0]?.url).toBe("/v1/baskets/B-1%2F..%2Fx/lines/0");
  });
});

describe("dish job calls", () => {
  it("GET and POST …/run on the job's path, with the id encoded", async () => {
    const sent = fakeFetch(200, { job_id: "DJ-1", state: "done" });
    await api.dishJob("DJ-1");
    await api.runDishJob("DJ/1");
    expect(sent).toEqual([
      { url: "/v1/baskets/dish-jobs/DJ-1", method: "GET", body: undefined },
      { url: "/v1/baskets/dish-jobs/DJ%2F1/run", method: "POST", body: undefined },
    ]);
  });
});

describe("approval and order calls", () => {
  it("list, decide, order and audit use the documented routes, with a flat decision body", async () => {
    const sent = fakeFetch(200, { events: [] });
    await api.approvals();
    await api.decide("AP-1/2", "reject", "");
    await api.order("O-1A2B3C4D5E");
    await api.orderAudit("O-1A2B3C4D5E");
    expect(sent.map((s) => `${s.method} ${s.url}`)).toEqual([
      "GET /v1/approvals", "POST /v1/approvals/AP-1%2F2/decision", "GET /v1/orders/O-1A2B3C4D5E",
      "GET /v1/orders/O-1A2B3C4D5E/audit",
    ]);
    expect(sent[1]?.body).toEqual({ decision: "reject", comment: "" });
  });
  it("the audit route answering 404 means no timeline yet, not an error", async () => {
    fakeFetch(404, { detail: "Not Found" });
    await expect(api.orderAudit("O-1A2B3C4D5E")).resolves.toBeNull();
  });
  it("a 403 on the decision route still throws, with its status", async () => {
    fakeFetch(403, { detail: "approver role required" });
    const e = await api.decide("AP-1", "approve", "ok").catch((x: unknown) => x);
    expect(e).toBeInstanceOf(HttpError);
    expect((e as HttpError).status).toBe(403);
  });
});
