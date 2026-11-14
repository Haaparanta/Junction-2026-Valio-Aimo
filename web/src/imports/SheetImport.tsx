/**
 * Import list (docs/basket-plan.md M25.5): an .xlsx or .csv file, chosen with a button or dropped on the zone, goes
 * to the gateway, which matches and prices every row into the basket. Keyboard users use the button; the zone is a
 * mouse convenience. One file at a time. The gateway's answer goes to onImported; ImportSummary shows it.
 */
import { useEffect, useId, useRef, useState, type ChangeEvent, type DragEvent } from "react";
import type { ImportResponse } from "../api";
import { ONE_FILE, SHEET_ACCEPT, sheetFileProblem } from "./files";
import { IntakeError, TEMPLATE_CSV, TEMPLATE_XLSX, basketTarget, errorText, importSheet } from "./intakeApi";
import "./imports.css";

export type SheetImportProps = {
  /** The basket in focus; null starts a new basket. */
  basketId: string | null;
  /** Called with the gateway's answer after a successful import. */
  onImported: (response: ImportResponse) => void;
  /** "large" (default): the drop zone for the empty state. "compact": one row for the basket card. */
  variant?: "large" | "compact";
  /** True while the basket must not change, for example while an order is being placed. */
  disabled?: boolean;
};

const hasFiles = (e: { dataTransfer: DataTransfer | null }) =>
  e.dataTransfer !== null && Array.from(e.dataTransfer.types).includes("Files");

/** While a drop zone is on screen, a file dropped next to it does nothing, instead of the tab opening the file. */
function useStrayDropGuard() {
  useEffect(() => {
    const ignore = (e: globalThis.DragEvent) => {
      if (hasFiles(e)) e.preventDefault();
    };
    window.addEventListener("dragover", ignore);
    window.addEventListener("drop", ignore);
    return () => {
      window.removeEventListener("dragover", ignore);
      window.removeEventListener("drop", ignore);
    };
  }, []);
}

export function SheetImport({ basketId, onImported, variant = "large", disabled = false }: SheetImportProps) {
  const input = useRef<HTMLInputElement>(null);
  const depth = useRef(0); // dragenter and dragleave also fire for the zone's children
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState<string | null>(null);
  const hint = useId();
  useStrayDropGuard();
  const locked = busy || disabled;

  const start = async (file: File) => {
    const problem = sheetFileProblem(file);
    if (problem) {
      setError(problem);
      setStatus("");
      return;
    }
    setBusy(true);
    setError(null);
    setStatus("Importing the list: the gateway matches and prices every row…");
    let response: ImportResponse;
    try {
      response = await importSheet(file, basketTarget(basketId));
    } catch (e) {
      if (!(e instanceof IntakeError)) console.error(e);
      setError(errorText(e));
      setStatus("");
      return;
    } finally {
      setBusy(false);
    }
    setStatus(response.message_for_user.en);
    onImported(response); // outside the try: a failing page callback is not an import error
  };

  const pick = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.item(0) ?? null;
    e.target.value = ""; // so the same file can be chosen again after a fix
    if (file && !locked) void start(file);
  };
  const dragEnter = (e: DragEvent<HTMLDivElement>) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    depth.current += 1;
    if (!locked) setOver(true);
  };
  const dragOver = (e: DragEvent<HTMLDivElement>) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = locked ? "none" : "copy";
  };
  const dragLeave = (e: DragEvent<HTMLDivElement>) => {
    if (!hasFiles(e)) return;
    depth.current = Math.max(0, depth.current - 1);
    if (depth.current === 0) setOver(false);
  };
  const drop = (e: DragEvent<HTMLDivElement>) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    depth.current = 0;
    setOver(false);
    if (locked) return;
    const file = e.dataTransfer.files.item(0);
    if (e.dataTransfer.files.length !== 1 || !file) {
      setError(ONE_FILE);
      setStatus("");
      return;
    }
    void start(file);
  };

  const large = variant === "large";
  // aria-disabled, not disabled, while importing: a disabled button would drop keyboard focus to the page.
  const button = (
    <button type="button" className={large ? "primary intake-cta" : "primary"} disabled={disabled}
            aria-disabled={busy || undefined} aria-describedby={hint} onClick={() => { if (!locked) input.current?.click(); }}>
      {busy ? "Importing…" : "Import list"}
    </button>
  );
  const templates = (
    <>
      Templates: <a href={TEMPLATE_XLSX} download>Excel (.xlsx)</a> · <a href={TEMPLATE_CSV} download>CSV</a>
    </>
  );
  return (
    <div className={`intake-drop ${large ? "large" : "compact"}${over ? " over" : ""}`} aria-busy={busy}
         onDragEnter={dragEnter} onDragOver={dragOver} onDragLeave={dragLeave} onDrop={drop}>
      {large ? (
        <>
          <p className="intake-p intake-drop-title">Drop an Excel or CSV list here</p>
          <p id={hint} className="intake-p intake-hint">
            One .xlsx or .csv file, up to 200 rows. The gateway matches and prices every row into the basket.
          </p>
          {button}
          <p className="intake-p intake-templates">{templates}</p>
        </>
      ) : (
        <>
          {button}
          <span id={hint} className="intake-hint">or drop an .xlsx or .csv file here</span>
          <span className="intake-templates">{templates}</span>
        </>
      )}
      <input ref={input} type="file" accept={SHEET_ACCEPT} hidden tabIndex={-1} onChange={pick} />
      <p className={`intake-status${busy ? " intake-spin" : ""}`} role="status">{status}</p>
      {error && <p className="error intake-error" role="alert">{error}</p>}
    </div>
  );
}
