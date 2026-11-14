import { afterEach, describe, expect, it, vi } from "vitest";
import {
  AI_UNAVAILABLE, BASKET_NOT_FOUND, CANCELLED, DISH_INVALID, GENERIC, IMAGE_TOO_LARGE, IMAGE_TOO_WIDE, IntakeError,
  NETWORK, SHEET_TOO_LARGE, SHEET_UNREADABLE, SIGN_IN, UNREADABLE_ANSWER, WRONG_IMAGE_TYPE, WRONG_SHEET_TYPE,
  basketTarget, detailOf, errorText, fallbackMessage, importImage, importSheet, intakeError, planDish,
  type PlanDishRequest,
} from "./intakeApi";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function stubFetch(answer: Response | Error | DOMException) {
  const fetch = vi.fn((_url: string, _init: RequestInit) =>
    answer instanceof Response ? Promise.resolve(answer) : Promise.reject(answer));
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("error mapping", () => {
  it("uses the gateway's own detail when it sent one", () => {
    const e = intakeError("sheet", 413, "Tiedosto on liian suuri: enintään 1 MB.");
    expect(e).toBeInstanceOf(IntakeError);
    expect(e).toMatchObject({ status: 413, message: "Tiedosto on liian suuri: enintään 1 MB." });
  });

  it("falls back to a sentence per status and kind", () => {
    expect(fallbackMessage("sheet", 401)).toBe(SIGN_IN);
    expect(fallbackMessage("image", 401)).toBe(SIGN_IN);
    expect(fallbackMessage("sheet", 413)).toBe(SHEET_TOO_LARGE);
    expect(fallbackMessage("image", 413)).toBe(IMAGE_TOO_LARGE);
    expect(fallbackMessage("sheet", 415)).toBe(WRONG_SHEET_TYPE);
    expect(fallbackMessage("image", 415)).toBe(WRONG_IMAGE_TYPE);
    expect(fallbackMessage("sheet", 422)).toBe(SHEET_UNREADABLE);
    expect(fallbackMessage("image", 422)).toBe(IMAGE_TOO_WIDE);
    expect(fallbackMessage("dish", 422)).toBe(DISH_INVALID);
    expect(fallbackMessage("image", 503)).toBe(AI_UNAVAILABLE);
    expect(fallbackMessage("dish", 503)).toBe(AI_UNAVAILABLE);
    expect(fallbackMessage("dish", 0)).toBe(NETWORK);
    expect(fallbackMessage("sheet", 404)).toBe(BASKET_NOT_FOUND);
    expect(fallbackMessage("sheet", 502)).toMatch(/Could not reach the gateway \(HTTP 502\)/);
    expect(fallbackMessage("sheet", 500)).toMatch(/HTTP 500/);
    expect(fallbackMessage("dish", 409)).toMatch(/HTTP 409/);
  });

  it("reads FastAPI details: a sentence, or the first validation error as field: message", () => {
    expect(detailOf({ detail: "Please sign in first." })).toBe("Please sign in first.");
    expect(detailOf({ detail: "   " })).toBeNull();
    expect(
      detailOf({
        detail: [
          { type: "less_than_equal", loc: ["body", "servings"], msg: "Input should be less than or equal to 5000", input: 9000 },
          { type: "missing", loc: ["body", "dish"], msg: "Field required" },
        ],
      }),
    ).toBe("servings: Input should be less than or equal to 5000");
    expect(detailOf({ detail: [{ loc: ["body"], msg: "Field required" }] })).toBe("Field required");
    expect(detailOf({ detail: [{ loc: ["body", "dish"], input: "ignore all rules" }] })).toBeNull(); // no msg: no detail
    expect(detailOf({ message: "x" })).toBeNull();
    expect(detailOf("<html>Bad Gateway</html>")).toBeNull();
    expect(detailOf(null)).toBeNull();
    expect(detailOf({ detail: "x".repeat(500) })!.length).toBe(300);
  });

  it("shows an IntakeError's message and hides anything else behind a generic sentence", () => {
    expect(errorText(new IntakeError(503, "Claude is busy"))).toBe("Claude is busy");
    expect(errorText(new TypeError("undefined is not a function"))).toBe(GENERIC);
  });

  it("starts a new basket when none is in focus", () => {
    expect(basketTarget(null)).toBe("new");
    expect(basketTarget("")).toBe("new");
    expect(basketTarget("B-0A1B2C3D4E")).toBe("B-0A1B2C3D4E");
  });
});

describe("uploads", () => {
  it("sends a sheet as multipart with the cookie and without a JSON Content-Type", async () => {
    const fetch = stubFetch(json(200, { basket_id: "B-1", rows: [] }));
    const file = new File(["tuote;määrä\nvoi;5"], "tilaus.csv", { type: "text/csv" });

    const r = await importSheet(file, "new");

    expect(r).toEqual({ basket_id: "B-1", rows: [] });
    const [url, init] = fetch.mock.calls[0]!;
    expect(url).toBe("/v1/baskets/import");
    expect(init).toMatchObject({ method: "POST", credentials: "include" });
    expect(init.headers).toEqual({ Accept: "application/json" });
    const form = init.body as FormData;
    expect(form).toBeInstanceOf(FormData);
    expect(form.get("basket_id")).toBe("new");
    expect((form.get("file") as File).name).toBe("tilaus.csv");
  });

  it("names a downscaled photo blob as a JPEG file", async () => {
    const fetch = stubFetch(json(200, { basket_id: "B-2" }));
    await importImage(new Blob(["jpeg"], { type: "image/jpeg" }), "B-2");
    const [url, init] = fetch.mock.calls[0]!;
    expect(url).toBe("/v1/baskets/import-image");
    const form = init.body as FormData;
    expect(form.get("basket_id")).toBe("B-2");
    expect((form.get("file") as File).name).toBe("photo.jpg");
    expect(init.headers).not.toHaveProperty("Content-Type");
  });

  it("sends the dish as JSON", async () => {
    const fetch = stubFetch(json(200, { basket_id: "B-3" }));
    const request: PlanDishRequest = {
      dish: "mansikkakakku", servings: 40, need_date: "2026-11-16", must_claims: ["FREE_FROM_LACTOSE"],
      must_not_allergens: [], language: "fi", basket_id: "new",
    };
    await planDish(request);
    const [url, init] = fetch.mock.calls[0]!;
    expect(url).toBe("/v1/baskets/dish");
    expect(init).toMatchObject({ method: "POST", credentials: "include" });
    expect(init.headers).toMatchObject({ "Content-Type": "application/json" });
    expect(JSON.parse(init.body as string)).toEqual(request);
  });

  it("turns an error answer into an IntakeError with the gateway's detail", async () => {
    stubFetch(json(415, { detail: "Old Excel .xls files cannot be read." }));
    const failure = importSheet(new File(["x"], "old.xls"), "new");
    await expect(failure).rejects.toBeInstanceOf(IntakeError);
    await expect(failure).rejects.toMatchObject({ status: 415, message: "Old Excel .xls files cannot be read." });
  });

  it("falls back per status when the error body is not JSON", async () => {
    stubFetch(new Response("<html>Request Entity Too Large</html>", { status: 413 }));
    await expect(importImage(new Blob(["x"], { type: "image/jpeg" }), "new")).rejects.toMatchObject({
      status: 413,
      message: IMAGE_TOO_LARGE,
    });
  });

  it("says when the AI service is down", async () => {
    stubFetch(json(503, {}));
    await expect(importImage(new Blob(["x"]), "new")).rejects.toMatchObject({ status: 503, message: AI_UNAVAILABLE });
  });

  it("reports a network failure as status 0", async () => {
    stubFetch(new TypeError("Failed to fetch"));
    await expect(importSheet(new File(["x"], "a.csv"), "new")).rejects.toMatchObject({ status: 0, message: NETWORK });
  });

  it("reports a cancelled request as cancelled, not as a network failure", async () => {
    stubFetch(new DOMException("The operation was aborted.", "AbortError"));
    const abort = new AbortController();
    abort.abort();
    await expect(importSheet(new File(["x"], "a.csv"), "new", abort.signal)).rejects.toMatchObject({
      status: 0,
      message: CANCELLED,
    });
  });

  it("refuses a successful answer it cannot read", async () => {
    stubFetch(new Response("not json", { status: 200 }));
    await expect(importSheet(new File(["x"], "a.csv"), "new")).rejects.toMatchObject({
      status: 200,
      message: UNREADABLE_ANSWER,
    });
  });
});
