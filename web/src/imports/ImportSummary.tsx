/**
 * What an import did (docs/basket-plan.md M25.5, M28.5): a heading from the gateway's counts, then the rows that need
 * the buyer, each a button to its basket line. Rows from a photo also show the text as read and a confidence chip.
 * Cell text and photo text are data: they are rendered as text only.
 */
import { useId } from "react";
import type { Confidence, ImportResponse, ImportRow } from "../api";
import {
  CONFIDENCE_CHIP, STATUS_CHIP, attentionFirst, confidenceFor, needsAttention, notAddedText, summaryText,
} from "./summary";
import "./imports.css";

export type ImportSummaryProps = {
  /** The answer of an import (importSheet or importImage), as onImported received it. */
  response: ImportResponse;
  /** Shows that basket line, for example by scrolling to it and opening its editor. */
  onShowLine: (lineId: number) => void;
};

function SummaryRow({ row, photo, confidence, onShowLine }: {
  row: ImportRow; photo: boolean; confidence: Confidence | null; onShowLine: (lineId: number) => void;
}) {
  const why = useId();
  const lineId = row.line_id;
  return (
    <li className={`intake-row s-${row.status}`}>
      <button type="button" className="intake-row-btn" disabled={lineId === null}
              aria-describedby={lineId === null ? why : undefined}
              onClick={() => { if (lineId !== null) onShowLine(lineId); }}>
        <span className="intake-row-top">
          <span className="intake-rownum">Row {row.row_number}</span>
          <span className={`chip intake-chip s-${row.status}`}>{STATUS_CHIP[row.status] ?? row.status}</span>
          {confidence && <span className={`chip intake-chip c-${confidence}`}>{CONFIDENCE_CHIP[confidence]}</span>}
        </span>
        <span className="intake-raw">{photo ? "Read as " : ""}“{row.raw_text}”</span>
        <span className="intake-msg">{row.message.en}</span>
        {lineId !== null && <span className="intake-go">Show line {lineId}</span>}
      </button>
      {lineId === null && <p id={why} className="intake-why">{notAddedText(photo)}</p>}
    </li>
  );
}

export function ImportSummary({ response, onShowLine }: ImportSummaryProps) {
  const heading = useId();
  const text = summaryText(response.counts);
  const photo = response.extraction !== null;
  const rows = attentionFirst(response.rows);
  const open = rows.filter(needsAttention);
  const priced = rows.filter((r) => !needsAttention(r));
  const item = (r: ImportRow) => (
    <SummaryRow key={`${r.row_number}:${r.line_id ?? "-"}`} row={r} photo={photo}
                confidence={photo ? confidenceFor(r, response) : null} onShowLine={onShowLine} />
  );
  return (
    <section className="card intake-summary" aria-labelledby={heading}>
      <header>
        <span className="tier">{photo ? "Read from a photo" : "Imported list"}</span>
        <span className="pid">{response.basket_id}</span>
      </header>
      <h2 id={heading}>{text.en}</h2>
      <p className="intake-fi" lang="fi">{text.fi}</p>
      {open.length > 0 && (
        <>
          <h3>Needs your attention</h3>
          <ol className="intake-rows">{open.map(item)}</ol>
        </>
      )}
      {priced.length > 0 && (
        <details open={open.length === 0}>
          <summary>Priced rows ({response.counts.priced ?? priced.length})</summary>
          <ol className="intake-rows">{priced.map(item)}</ol>
        </details>
      )}
    </section>
  );
}
