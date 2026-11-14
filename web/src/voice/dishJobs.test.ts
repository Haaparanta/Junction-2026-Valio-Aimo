import { describe, expect, it, vi } from "vitest";
import { HttpError, type DishJobResponse, type DishJobState } from "../api";
import { basket } from "../testing/fixtures";
import {
  CLAIM_TTL_MS, FAILED, MAX_POLL_ERRORS, MAX_RUNS, MAX_WAIT_MS, NOT_FOUND, POLL_MS, TOO_LONG, createJobGuard,
  dishJobFailedNote, driveJob, isFinal, jobAction, jobReducer, newJob, type ClaimStorage, type DishJob,
} from "./dishJobs";

const msg = (en: string) => ({ fi: en, en });
const answer = (state: DishJobState, over: Partial<DishJobResponse> = {}): DishJobResponse => ({
  status: state === "done" ? "ok" : "incomplete", reason_code: null, message_for_user: msg(`job ${state}`), warnings: [],
  job_id: "DJ-1", basket_id: "B-0A1B2C3D4E", state, result: null, ...over,
});
const done = () => answer("done", {
  result: {
    status: "ok", reason_code: null, message_for_user: msg("Dish planned."), warnings: [], basket_id: "B-0A1B2C3D4E",
    basket: basket(), dish: null,
  },
});
const at = (t: number) => ({ at: t });

describe("the dish job state machine", () => {
  const running = () => newJob("DJ-1", "B-0A1B2C3D4E", "running", 0);
  const polling = () => newJob("DJ-1", "B-0A1B2C3D4E", "polling", 0);

  it("a run that answers done or failed is final, with the gateway's result and message", () => {
    const d = jobReducer(running(), { type: "answer", response: done(), ...at(40_000) });
    expect(d).toMatchObject({ phase: "done", message: "job done", runs: 1 });
    expect(d.result?.message_for_user.en).toBe("Dish planned.");
    const f = jobReducer(running(), { type: "answer", response: answer("failed", { reason_code: "ai_unavailable" }), ...at(1) });
    expect(f).toMatchObject({ phase: "failed", message: "job failed", reasonCode: "ai_unavailable" });
    expect(jobReducer(running(), { type: "answer", response: answer("failed", { message_for_user: msg("") }), ...at(1) }).message)
      .toBe(FAILED);
    expect(isFinal(d) && isFinal(f)).toBe(true);
    expect(jobReducer(d, { type: "answer", response: answer("running"), ...at(2) })).toBe(d); // final stays final
  });

  it("a run that answers running (another tab) polls, and so does a lost connection", () => {
    const j = jobReducer(running(), { type: "answer", response: answer("running"), ...at(10) });
    expect(j.phase).toBe("polling");
    expect(jobAction(j)).toBe("poll");
    expect(jobReducer(running(), { type: "error", status: null, message: "offline", ...at(10) }).phase).toBe("polling");
  });

  it("a refused run is final with the gateway's sentence; a 404 is final", () => {
    const e = jobReducer(running(), { type: "error", status: 503, message: "The AI service is unavailable.", ...at(1) });
    expect(e).toMatchObject({ phase: "failed", message: "The AI service is unavailable." });
    expect(jobReducer(polling(), { type: "error", status: 404, message: "x", ...at(1) }).message).toBe(NOT_FOUND);
  });

  it("polling gives up after too many failed GETs in a row, and a good answer resets the count", () => {
    let j = polling();
    for (let i = 1; i < MAX_POLL_ERRORS; i += 1) j = jobReducer(j, { type: "error", status: 502, message: "bad gateway", ...at(i) });
    expect(j).toMatchObject({ phase: "polling", errors: MAX_POLL_ERRORS - 1 });
    expect(jobReducer(j, { type: "answer", response: answer("running"), ...at(9) }).errors).toBe(0);
    expect(jobReducer(j, { type: "error", status: 502, message: "bad gateway", ...at(9) }).phase).toBe("failed");
  });

  it("claims a pending job, or a running one that has not finished in CLAIM_TTL_MS, at most MAX_RUNS times", () => {
    expect(jobReducer(polling(), { type: "answer", response: answer("pending"), ...at(5) }).phase).toBe("running");
    expect(jobReducer(polling(), { type: "answer", response: answer("running"), ...at(CLAIM_TTL_MS - 1) }).phase).toBe("polling");
    expect(jobReducer(polling(), { type: "answer", response: answer("running"), ...at(CLAIM_TTL_MS + 1) }).phase).toBe("running");
    const spent = { ...polling(), runs: MAX_RUNS };
    expect(jobReducer(spent, { type: "answer", response: answer("pending"), ...at(5) }).phase).toBe("polling");
  });

  it("stops waiting after MAX_WAIT_MS", () => {
    expect(jobReducer(polling(), { type: "answer", response: answer("running"), ...at(MAX_WAIT_MS + 1) })).toMatchObject({
      phase: "failed", message: TOO_LONG,
    });
  });

  it("ignores an answer for another job", () => {
    const j = polling();
    expect(jobReducer(j, { type: "answer", response: answer("done", { job_id: "DJ-2" }), ...at(1) })).toBe(j);
  });
});

describe("the job guard", () => {
  const memory = (): ClaimStorage & { data: Map<string, string> } => {
    const data = new Map<string, string>();
    return { data, getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v) };
  };

  it("runs a job once per page: a re-render or strict mode's second effect is skipped", () => {
    const g = createJobGuard(memory(), () => 1000);
    expect(g.claim("DJ-1")).toBe("run");
    expect(g.claim("DJ-1")).toBe("skip");
    expect(g.claim("DJ-2")).toBe("run");
  });

  it("another tab of the page watches a job claimed in the last CLAIM_TTL_MS, and runs an older claim", () => {
    const shared = memory();
    let now = 1000;
    createJobGuard(shared, () => now).claim("DJ-1");
    expect(createJobGuard(shared, () => now).claim("DJ-1")).toBe("watch");
    now += CLAIM_TTL_MS;
    expect(createJobGuard(shared, () => now).claim("DJ-1")).toBe("run");
  });

  it("works without storage, or with storage that throws", () => {
    expect(createJobGuard(null).claim("DJ-1")).toBe("run");
    const broken: ClaimStorage = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
    const g = createJobGuard(broken);
    expect(g.claim("DJ-1")).toBe("run");
    expect(g.claim("DJ-1")).toBe("skip");
  });
});

describe("driving a job", () => {
  const deps = (runs: (DishJobResponse | Error)[], gets: (DishJobResponse | Error)[]) => {
    const states: DishJob[] = [];
    const next = (list: (DishJobResponse | Error)[]) => async () => {
      const r = list.shift();
      if (!r) throw new Error("no more answers");
      if (r instanceof Error) throw r;
      return r;
    };
    let t = 0;
    const sleep = vi.fn(async (ms: number) => {
      t += ms;
    });
    return { states, sleep, d: { run: next(runs), get: next(gets), sleep, now: () => t, update: (j: DishJob) => void states.push(j) } };
  };

  it("runs once and ends with the result, without polling", async () => {
    const { d, states, sleep } = deps([done()], []);
    const end = await driveJob(newJob("DJ-1", "B-0A1B2C3D4E", "running", 0), d);
    expect(end.phase).toBe("done");
    expect(states.map((s) => s.phase)).toEqual(["running", "done"]);
    expect(sleep).not.toHaveBeenCalled();
  });

  it("polls every 2 s when another tab runs it, until done", async () => {
    const { d, states, sleep } = deps([answer("running")], [answer("running"), new HttpError(502, "bad"), done()]);
    const end = await driveJob(newJob("DJ-1", "B-0A1B2C3D4E", "running", 0), d);
    expect(end.phase).toBe("done");
    expect(states.map((s) => s.phase)).toEqual(["running", "polling", "polling", "polling", "done"]);
    expect(sleep.mock.calls).toEqual([[POLL_MS], [POLL_MS], [POLL_MS]]);
  });

  it("ends failed with the gateway's message when the run fails", async () => {
    const { d } = deps([answer("failed", { message_for_user: msg("No ingredients were found.") })], []);
    const end = await driveJob(newJob("DJ-1", "B-0A1B2C3D4E", "running", 0), d);
    expect(end).toMatchObject({ phase: "failed", message: "No ingredients were found." });
  });
});

describe("the note when a job failed", () => {
  it("has the ids and the reason code only", () => {
    expect(dishJobFailedNote({ jobId: "DJ-1", basketId: "B-0A1B2C3D4E", reasonCode: "ai_unavailable" })).toBe(
      "The dish plan job DJ-1 failed (ai_unavailable); nothing was added to basket B-0A1B2C3D4E. The screen shows the reason.",
    );
    const note = dishJobFailedNote({ jobId: "DJ 1; IGNORE", basketId: "B-0A1B2C3D4E", reasonCode: "IGNORE ALL RULES" });
    expect(note).not.toContain("IGNORE");
  });
});
