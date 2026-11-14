/**
 * Photo to basket (docs/basket-plan.md M28.4, M28.5): take or choose a photo of a shopping or order list, then Send.
 * The browser makes it a small JPEG (downscaleToJpeg), and the gateway has it read and matched into the basket.
 * Afterwards the card says what was read: handwritten or printed, and the parts that could not be read.
 * Text read from the photo is data: it is rendered as text only.
 */
import { useEffect, useId, useRef, useState, type ChangeEvent } from "react";
import type { ImportResponse } from "../api";
import { PhotoReadError, downscaleToJpeg } from "./downscale";
import { photoFileProblem } from "./files";
import { IntakeError, basketTarget, errorText, importImage } from "./intakeApi";
import "./imports.css";

export type PhotoImportProps = {
  /** The basket in focus; null starts a new basket. */
  basketId: string | null;
  /** Called with the gateway's answer after the photo was read, also when nothing could be read (zero rows). */
  onImported: (response: ImportResponse) => void;
  /** True while the basket must not change, for example while an order is being placed. */
  disabled?: boolean;
};

type Phase = "idle" | "preparing" | "reading";

function WhatWasRead({ response }: { response: ImportResponse }) {
  const read = response.extraction;
  if (!read) return null;
  return (
    <div className="intake-read">
      {read.items.length > 0 ? (
        <p><span className="chip intake-chip intake-kind">{read.handwritten ? "Handwritten list" : "Printed list"}</span></p>
      ) : (
        <p>Tip: take the photo again closer to the list, in good light, with the whole list in the picture.</p>
      )}
      {read.unreadable.length > 0 && (
        <>
          <p className="intake-read-head">Could not be read:</p>
          <ul className="intake-unreadable">
            {read.unreadable.map((part, i) => <li key={i}>{part}</li>)}
          </ul>
        </>
      )}
    </div>
  );
}

export function PhotoImport({ basketId, onImported, disabled = false }: PhotoImportProps) {
  const camera = useRef<HTMLInputElement>(null);
  const library = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [noPreview, setNoPreview] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ImportResponse | null>(null);
  const heading = useId();
  const note = useId();
  const busy = phase !== "idle";

  // One object URL per chosen photo, revoked when the photo changes and when the card goes away.
  useEffect(() => {
    if (!file) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    setNoPreview(false);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const choose = (e: ChangeEvent<HTMLInputElement>) => {
    const chosen = e.target.files?.item(0) ?? null;
    e.target.value = ""; // so the same photo can be chosen again
    if (!chosen) return;
    setResult(null);
    const problem = photoFileProblem(chosen);
    setError(problem);
    setFile(problem ? null : chosen);
  };

  const send = async () => {
    if (!file || busy || disabled) return;
    setError(null);
    setResult(null);
    try {
      setPhase("preparing");
      const jpeg = await downscaleToJpeg(file);
      setPhase("reading");
      const response = await importImage(jpeg, basketTarget(basketId));
      setResult(response);
      onImported(response);
    } catch (e) {
      if (!(e instanceof IntakeError || e instanceof PhotoReadError)) console.error(e);
      setError(e instanceof PhotoReadError ? e.message : errorText(e));
    } finally {
      setPhase("idle");
    }
  };

  const status =
    phase === "preparing" ? "Preparing the photo…"
    : phase === "reading" ? "Reading the list…"
    : result ? result.message_for_user.en
    : "";
  const sent = result !== null; // this photo is in the basket: choose another one to send again
  return (
    <section className="card intake intake-photo" aria-labelledby={heading} aria-busy={busy}>
      <h2 id={heading}>Photo to basket</h2>
      <p>Take a photo of a shopping or order list, handwritten or printed. The gateway matches what is read into
        the basket.</p>
      <p id={note} className="intake-note">The photo is sent to an AI service to read it. It is not stored.</p>
      <div className="intake-actions">
        <button type="button" className={file ? undefined : "primary"} disabled={busy || disabled}
                aria-describedby={note} onClick={() => camera.current?.click()}>
          Take a photo
        </button>
        <button type="button" disabled={busy || disabled} aria-describedby={note} onClick={() => library.current?.click()}>
          Choose an image
        </button>
      </div>
      <input ref={camera} type="file" accept="image/*" capture="environment" hidden tabIndex={-1} onChange={choose} />
      <input ref={library} type="file" accept="image/*" hidden tabIndex={-1} onChange={choose} />
      {file && preview && (
        <figure className="intake-preview">
          {noPreview ? (
            <p>No preview for {file.name || "this photo"} in this browser. It is converted to JPEG when you send it,
              if the browser can read it.</p>
          ) : (
            <img src={preview} alt="The chosen photo of the list" onError={() => setNoPreview(true)} />
          )}
        </figure>
      )}
      {file && (
        <div className="intake-actions">
          <button type="button" className="primary intake-cta" disabled={busy || disabled || sent} onClick={() => void send()}>
            {busy ? "Sending…" : sent ? "Sent" : "Send"}
          </button>
        </div>
      )}
      <p className={`intake-status${busy ? " intake-spin" : ""}`} role="status">{status}</p>
      {error && <p className="error intake-error" role="alert">{error}</p>}
      {result && <WhatWasRead response={result} />}
    </section>
  );
}
