/**
 * The voice path of plan_dish (docs/basket-plan.md M27): the agent's tool answers at once with a job, because
 * Claude needs 35-51 s and a voice tool call must answer in about 20 s. The open page runs the job: whenever the
 * basket on screen lists dish_jobs, POST …/run once per job (the gateway claims it atomically and plans the dish
 * inside that request). A job another tab already runs answers "running": then GET it every 2 s until it is done
 * or failed.
 *
 * Pure parts (the claim guard, the reducer, the next action) are separate from driveJob, which takes its gateway
 * calls, clock and timer as arguments, so all of it is tested without a browser.
 */
import { HttpError, errorText, type DishJobResponse, type DishResponse } from "../api";

export const POLL_MS = 2000;
/** The gateway lets another request take over a running job after 180 s; a claim in this browser lasts as long. */
export const CLAIM_TTL_MS = 180_000;
/** Polling gives up after this many failed GETs in a row, or after MAX_WAIT_MS in all. */
export const MAX_POLL_ERRORS = 5;
export const MAX_WAIT_MS = 5 * 60_000;
/** At most this many POST …/run per job and page: the first, and one take-over of a pending or stale job. */
export const MAX_RUNS = 2;
export const PLANNING_TEXT = "Planning the dish, about half a minute…";
export const TOO_LONG = "The dish plan is taking too long. Ask again, or use the dish form on screen.";
export const NOT_FOUND = "This dish plan was not found. Ask again, or use the dish form on screen.";
export const FAILED = "The dish could not be planned. Ask again, or use the dish form on screen.";

/** running: this page's POST …/run is out; polling: GET every 2 s; done and failed are final. */
export type JobPhase = "running" | "polling" | "done" | "failed";

export type DishJob = {
  jobId: string;
  basketId: string;
  phase: JobPhase;
  /** The gateway's message (or a page sentence for a failure it could not report). */
  message: string;
  reasonCode: string | null;
  result: DishResponse | null;
  /** Failed GETs in a row while polling. */
  errors: number;
  /** POST …/run requests this page sent for the job. */
  runs: number;
  startedAt: number;
  /** The final state was told to the agent (or there was no call to tell). */
  announced: boolean;
};

export type JobEvent =
  | { type: "answer"; response: DishJobResponse; at: number }
  | { type: "error"; status: number | null; message: string; at: number };

export const isFinal = (j: Pick<DishJob, "phase">): boolean => j.phase === "done" || j.phase === "failed";

export function newJob(jobId: string, basketId: string, phase: "running" | "polling", at: number): DishJob {
  return {
    jobId, basketId, phase, message: "", reasonCode: null, result: null, errors: 0, runs: 0, startedAt: at, announced: false,
  };
}

const failed = (j: DishJob, message: string, reasonCode: string | null = j.reasonCode): DishJob =>
  ({ ...j, phase: "failed", message, reasonCode });

/** The next state after a gateway answer or a failed call. A final state never changes. */
export function jobReducer(prev: DishJob, ev: JobEvent): DishJob {
  if (isFinal(prev)) return prev;
  const j = prev.phase === "running" ? { ...prev, runs: prev.runs + 1 } : prev; // this event answers a run
  const overtime = ev.at - j.startedAt > MAX_WAIT_MS;
  if (ev.type === "error") {
    if (ev.status === 404) return failed(j, NOT_FOUND);
    // The run request itself was refused (401, 409, 503 …): the gateway's sentence. Only a lost connection polls.
    if (j.phase === "running" && ev.status !== null) return failed(j, ev.message || FAILED);
    const errors = j.errors + 1;
    if (errors >= MAX_POLL_ERRORS || overtime) return failed(j, `Could not check the dish plan: ${ev.message}`);
    return { ...j, phase: "polling", errors };
  }
  const r = ev.response;
  if (r.job_id !== j.jobId) return j;
  const message = r.message_for_user?.en ?? "";
  if (r.state === "done") {
    return { ...j, phase: "done", result: r.result ?? null, message, reasonCode: r.reason_code, errors: 0,
             basketId: r.basket_id || j.basketId };
  }
  if (r.state === "failed") return failed(j, message || FAILED, r.reason_code);
  if (overtime) return failed(j, TOO_LONG);
  // Nobody holds a pending job, and the gateway hands a running one over after CLAIM_TTL_MS: claim it then.
  const stale = r.state === "running" && ev.at - j.startedAt > CLAIM_TTL_MS;
  const claim = (r.state === "pending" || stale) && j.runs < MAX_RUNS;
  return { ...j, phase: claim ? "running" : "polling", message, errors: 0 };
}

export type JobAction = "run" | "poll" | "none";
export const jobAction = (j: Pick<DishJob, "phase">): JobAction =>
  j.phase === "running" ? "run" : j.phase === "polling" ? "poll" : "none";

/** localStorage, or anything shaped like it; it may throw (private windows, blocked storage). */
export type ClaimStorage = { getItem(key: string): string | null; setItem(key: string, value: string): void };

const CLAIM_KEY = "dish-job:";

/**
 * One claim per job and page: "run" means this page runs it; "watch" means another tab of this page claimed it in
 * the last CLAIM_TTL_MS, so this one polls; "skip" means this page already has it (a re-render or React strict mode
 * running an effect twice). The gateway's own atomic claim stays the real guard: a second run answers "running".
 */
export function createJobGuard(storage: ClaimStorage | null, now: () => number = Date.now) {
  const mine = new Set<string>();
  return {
    claim(jobId: string): "run" | "watch" | "skip" {
      if (mine.has(jobId)) return "skip";
      mine.add(jobId);
      try {
        const at = Number(storage?.getItem(CLAIM_KEY + jobId) ?? NaN);
        if (Number.isFinite(at) && now() - at >= 0 && now() - at < CLAIM_TTL_MS) return "watch";
        storage?.setItem(CLAIM_KEY + jobId, String(now()));
      } catch {
        /* no storage: the gateway's claim decides */
      }
      return "run";
    },
    has: (jobId: string) => mine.has(jobId),
  };
}

export type JobDeps = {
  run: (jobId: string) => Promise<DishJobResponse>;
  get: (jobId: string) => Promise<DishJobResponse>;
  sleep: (ms: number) => Promise<void>;
  now: () => number;
  /** Every state, the first one included. */
  update: (j: DishJob) => void;
};

/** Run or watch one job until it is done or failed; resolves to the final state. */
export async function driveJob(start: DishJob, deps: JobDeps): Promise<DishJob> {
  let j = start;
  deps.update(j);
  for (;;) {
    const action = jobAction(j);
    if (action === "none") return j;
    if (action === "poll") await deps.sleep(POLL_MS);
    try {
      const r = action === "run" ? await deps.run(j.jobId) : await deps.get(j.jobId);
      j = jobReducer(j, { type: "answer", response: r, at: deps.now() });
    } catch (e) {
      j = jobReducer(j, { type: "error", status: e instanceof HttpError ? e.status : null, message: errorText(e), at: deps.now() });
    }
    deps.update(j);
  }
}

/** The short factual note for the agent when a job failed: ids and the reason code only, never free text. */
export function dishJobFailedNote(j: Pick<DishJob, "jobId" | "basketId" | "reasonCode">): string {
  const id = (v: string) => (/^[A-Za-z0-9_-]{1,80}$/.test(v) ? v : "(unreadable id)");
  const code = j.reasonCode && /^[a-z_]{1,40}$/.test(j.reasonCode) ? ` (${j.reasonCode})` : "";
  return `The dish plan job ${id(j.jobId)} failed${code}; nothing was added to basket ${id(j.basketId)}. ` +
    "The screen shows the reason.";
}

/** What the agent hears as the buyer's nudge after a job is done, so it reads the plan out (as ApprovalCard does). */
export const DISH_READY_NUDGE = "The dish plan is on screen now.";
