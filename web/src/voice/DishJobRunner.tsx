/**
 * Runs the plan_dish jobs of the basket on screen (voice/dishJobs.ts). Each job runs outside React, so a re-render,
 * React strict mode or the card going away never runs it twice or drops its answer; the guard keeps one run per
 * job and page, and another tab of the page polls instead. When a job ends, the basket is fetched again and, during
 * a live call, the agent gets a silent note (dishNote, or the failure's ids and code) and, for a planned dish, a
 * short nudge so it reads the plan out, as ApprovalCard does for approvals.
 */
import { useEffect } from "react";
import { useConversationControls } from "@elevenlabs/react";
import { api } from "../api";
import { applyBasket, hasBasket, refreshBasket } from "../cards/actions";
import { dishNote } from "../imports/notes";
import {
  DISH_READY_NUDGE, createJobGuard, dishJobFailedNote, driveJob, isFinal, newJob, type ClaimStorage, type DishJob,
} from "./dishJobs";
import { markAnnounced, putJob, ui, useUi } from "./store";
import { useAgentNote } from "./useAgentNote";

const JOB_ID = /^[A-Za-z0-9_-]{1,80}$/;

function storage(): ClaimStorage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null; // storage blocked
  }
}

const guard = createJobGuard(storage());

/** The job ended: show the gateway's latest basket (the planned dish, or the job gone from dish_jobs). */
function settle(j: DishJob): void {
  if (j.phase === "done" && j.result && hasBasket(j.result)) applyBasket(j.result);
  void refreshBasket(j.basketId);
}

/** Start one job, once per page: run it here, or poll it when another tab of the page already runs it. */
export function startDishJob(jobId: string, basketId: string): void {
  if (!JOB_ID.test(jobId)) return;
  const claim = guard.claim(jobId);
  if (claim === "skip") return;
  const job = newJob(jobId, basketId, claim === "run" ? "running" : "polling", Date.now());
  void driveJob(job, {
    run: api.runDishJob,
    get: api.dishJob,
    sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    now: Date.now,
    update: (next) => ui.set((s) => putJob(s, next)),
  }).then(settle);
}

const NO_JOBS: string[] = [];

export function DishJobRunner() {
  const basketId = useUi((s) => (s.basket && s.basket.basket_id === s.basketId ? s.basketId : null));
  const listed = useUi((s) =>
    s.basket && s.basket.basket_id === s.basketId && Array.isArray(s.basket.dish_jobs) ? s.basket.dish_jobs : NO_JOBS);
  const jobs = useUi((s) => s.dishJobs);
  const live = useUi((s) => s.phase === "live");
  const notify = useAgentNote();
  const { sendUserMessage } = useConversationControls();

  useEffect(() => {
    if (basketId) for (const id of listed) startDishJob(id, basketId);
  }, [basketId, listed]);

  useEffect(() => {
    for (const seen of Object.values(jobs)) {
      // Read the store, not this render's snapshot: strict mode runs the effect twice with the same snapshot.
      const j = ui.get().dishJobs[seen.jobId];
      if (!j || !isFinal(j) || j.announced) continue;
      ui.set((s) => markAnnounced(s, j.jobId)); // first, so a second effect run does not tell it twice
      if (!live) continue;
      if (j.phase === "failed") {
        notify(dishJobFailedNote(j));
        continue;
      }
      if (j.result) notify(dishNote(j.result, "voice"));
      try {
        sendUserMessage(DISH_READY_NUDGE);
      } catch {
        /* the call just ended */
      }
    }
  }, [jobs, live, notify, sendUserMessage]);
  return null;
}
