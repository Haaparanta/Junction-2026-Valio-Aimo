/**
 * Aino and Mansikki on one layered SVG rig (our own drawing, see PROVENANCE.md). CSS variables from the
 * animation driver move the mouth, eyes and breathing; data attributes carry state, expression and persona.
 */
import { useEffect, useRef, useState } from "react";
import { useUi } from "../voice/store";
import { avatarState, expression } from "./state";
import { useAvatarDriver } from "./useAvatarDriver";

const LABEL: Record<string, string> = {
  idle: "Not in a call", connecting: "Connecting…", queued: "Waiting for a free line…", listening: "Listening",
  userSpeaking: "Hearing you", thinking: "Checking with the gateway…", speaking: "Speaking", error: "Connection problem",
};

function useNow(ms: number) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

export function Avatar() {
  const ref = useRef<SVGSVGElement>(null);
  useAvatarDriver(ref);
  const now = useNow(500);
  const persona = useUi((s) => s.persona);
  const state = avatarState(useUi((s) => s), now);
  const expr = expression(useUi((s) => s.lastOutcome), now);
  const name = persona === "cow" ? "Mansikki" : "Aino";

  return (
    <figure className="avatar" data-state={state}>
      <svg ref={ref} viewBox="0 0 240 240" role="img" aria-label={`${name}: ${LABEL[state]}`}
           data-persona={persona} data-state={state} data-expression={expr} data-mouth="M">
        <circle className="halo" cx="120" cy="120" r="112" />
        <g className="breathe">
          {persona === "cow" ? <CowHead /> : <AinoHead />}
        </g>
      </svg>
      <figcaption>
        <strong>{name}</strong> · <span aria-live="polite">{LABEL[state]}</span>
      </figcaption>
    </figure>
  );
}

function Eyes({ y, spread = 26, color = "#1d2433" }: { y: number; spread?: number; color?: string }) {
  return (
    <g className="eyes">
      {[-spread, spread].map((dx) => (
        <g key={dx} className="eye" transform={`translate(${120 + dx} ${y})`}>
          <ellipse className="eye-white" rx="11" ry="9" />
          <circle className="pupil" r="5.5" fill={color} />
          <circle r="1.8" cx="2" cy="-2" fill="#fff" />
        </g>
      ))}
    </g>
  );
}

function Mouth({ x, y, w }: { x: number; y: number; w: number }) {
  return (
    <g className="mouth" transform={`translate(${x} ${y})`}>
      <g className="mouth-inner">
        <ellipse rx={w} ry="10" className="mouth-cavity" />
        <path className="teeth" d={`M${-w * 0.7} -8 Q0 -4 ${w * 0.7} -8 L${w * 0.6} -4 Q0 -1 ${-w * 0.6} -4Z`} />
        <ellipse className="tongue" cx="0" cy="6" rx={w * 0.5} ry="4" />
      </g>
      <path className="lips-closed" d={`M${-w} 0 Q0 4 ${w} 0`} />
    </g>
  );
}

function AinoHead() {
  return (
    <g className="aino">
      <path className="hair-back" d="M52 118 C44 52 92 22 122 24 C162 24 198 52 190 122 L196 196 C170 212 70 212 44 196Z" />
      <rect className="neck" x="102" y="168" width="36" height="34" rx="10" />
      <path className="shirt" d="M58 240 C62 204 90 192 120 192 C150 192 178 204 182 240Z" />
      <ellipse className="ear" cx="62" cy="122" rx="10" ry="15" />
      <ellipse className="ear" cx="178" cy="122" rx="10" ry="15" />
      <path className="face" d="M64 112 C64 70 90 48 120 48 C150 48 176 70 176 112 C176 150 152 182 120 182 C88 182 64 150 64 112Z" />
      <path className="hair-front" d="M62 104 C62 60 96 40 124 42 C156 44 180 66 178 102 C160 88 140 70 132 58 C120 76 92 94 62 104Z" />
      <g className="brows">
        <path className="brow brow-l" d="M80 92 Q94 84 108 90" />
        <path className="brow brow-r" d="M132 90 Q146 84 160 92" />
      </g>
      <Eyes y={110} />
      <ellipse className="cheek" cx="84" cy="138" rx="10" ry="6" />
      <ellipse className="cheek" cx="156" cy="138" rx="10" ry="6" />
      <path className="nose" d="M120 116 Q114 134 121 138" />
      <Mouth x={120} y={156} w={16} />
      <circle className="badge" cx="150" cy="214" r="9" />
    </g>
  );
}

function CowHead() {
  return (
    <g className="cow">
      <path className="horn" d="M74 74 C60 52 62 36 74 28 C76 44 84 58 92 66Z" />
      <path className="horn" d="M166 74 C180 52 178 36 166 28 C164 44 156 58 148 66Z" />
      <g className="ear-l"><ellipse className="cow-ear" cx="46" cy="96" rx="26" ry="12" transform="rotate(-20 46 96)" /></g>
      <g className="ear-r"><ellipse className="cow-ear" cx="194" cy="96" rx="26" ry="12" transform="rotate(20 194 96)" /></g>
      <path className="cow-face" d="M66 104 C64 64 92 50 120 50 C148 50 176 64 174 104 L170 150 C168 176 72 176 70 150Z" />
      <path className="spot" d="M78 70 C92 60 108 66 104 84 C100 98 80 96 74 88Z" />
      <path className="spot" d="M150 60 C166 62 172 80 162 90 C152 96 140 84 144 72Z" />
      <path className="tuft" d="M106 54 Q112 40 120 52 Q126 40 134 54Z" />
      <g className="brows">
        <path className="brow brow-l" d="M84 90 Q96 84 108 90" />
        <path className="brow brow-r" d="M132 90 Q144 84 156 90" />
      </g>
      <Eyes y={106} spread={24} color="#3a2a1a" />
      <g className="jaw">
        <ellipse className="muzzle" cx="120" cy="156" rx="50" ry="34" />
        <ellipse className="nostril" cx="102" cy="146" rx="6" ry="8" />
        <ellipse className="nostril" cx="138" cy="146" rx="6" ry="8" />
        <Mouth x={120} y={170} w={20} />
      </g>
      <path className="strap" d="M84 192 Q120 206 156 192" />
      <g className="bell">
        <path d="M108 200 Q108 188 120 188 Q132 188 132 200 L136 218 L104 218Z" />
        <circle cx="120" cy="221" r="4" />
      </g>
    </g>
  );
}
