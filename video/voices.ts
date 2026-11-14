/**
 * Records the spoken lines with ElevenLabs (model eleven_v4, delivery tags such as [whispers]).
 * The words come from src/timeline.js; this file adds the casting and the tags.
 *
 *   node --env-file=.env.local video/voices.ts                 records every missing line
 *   node --env-file=.env.local video/voices.ts gymbro-deceive  records (again) the named lines
 *   node --env-file=.env.local video/voices.ts --cast          prints the casting and the models, records nothing
 *
 * Files go to video/audio/voice/<name>.mp3 and are committed, so rendering needs no key. The key is read from
 * the environment only (ELEVENLABS_API_KEY in the git-ignored .env.local); never put it in code.
 * Voices are cast by name from the account's pre-made voices, never by remembered ids. Rooms and the robot
 * filter are added in the mix (src/audio/mix.js), so the recordings stay dry.
 */
import { mkdirSync, existsSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { ElevenLabsClient } from "@elevenlabs/elevenlabs-js";
import { VOICE_LINES } from "./src/timeline.js";

type Cast = { voice: string; tags: string; stability?: number; text?: string };

/** Who says what, and how. Character voices: stability 0.3–0.4, similarity 0.8. */
const CAST: Record<string, Cast> = {
  "hook-host": { voice: "Liam", tags: "[excited] [shouting]", stability: 0.3 },
  "fridge-student": { voice: "Charlie", tags: "[confused] [fast]" },
  "fridge-whisper": { voice: "Charlie", tags: "[whispers] [fast]" },
  "napkin-organiser": { voice: "Jessica", tags: "[excited] [shouting]", stability: 0.3 },
  "clanker-buyer": { voice: "Will", tags: "[deadpan]" },
  "clanker-buyer2": { voice: "Will", tags: "[satisfied] [deadpan]" },
  "cake-chef": { voice: "Callum", tags: "[proud] [excited]" },
  "cake-back": { voice: "Callum", tags: "[relieved] [happy]" },
  "monday-aada": { voice: "Alice", tags: "[stressed] [fast]" },
  "monday-mikko": { voice: "Bill", tags: "[deadpan] [calm]", stability: 0.45 },
  "gymbro-bro": { voice: "Harry", tags: "[smug] [fast]" },
  "gymbro-deceive": { voice: "Harry", tags: "[innocent] [wide-eyed]" },
  "barn-robot": { voice: "River", tags: "[monotone] [robotic]", stability: 0.5 },
  "barn-ok": { voice: "River", tags: "[monotone]", stability: 0.5 },
  "galaxy-narrator": { voice: "Adam", tags: "[eerie] [slowly] [low voice]", stability: 0.4 },
};

const MODEL = "eleven_v4";
const OUT = join(import.meta.dirname, "audio", "voice");

function seedOf(name: string): number {
  let h = 7;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) % 4294967291;
  return h;
}

async function main() {
  const args = process.argv.slice(2);
  const castOnly = args.includes("--cast");
  const named = args.filter((a) => !a.startsWith("--"));
  const key = process.env.ELEVENLABS_API_KEY;
  if (!key) {
    console.error("ELEVENLABS_API_KEY is not set. Run from the repo root: node --env-file=.env.local video/voices.ts");
    process.exit(1);
  }
  const client = new ElevenLabsClient({ apiKey: key });

  const models = await client.models.list();
  const ids = models.map((m) => m.modelId);
  const model = ids.includes(MODEL) ? MODEL : ids.includes("eleven_v3") ? "eleven_v3" : ids[0];
  if (model !== MODEL) console.warn(`${MODEL} is not on this account; using ${model}`);

  const { voices } = await client.voices.getAll();
  const byName = (name: string) =>
    voices.find((v) => v.category === "premade" && v.name?.toLowerCase().startsWith(name.toLowerCase())) ??
    voices.find((v) => v.name?.toLowerCase().startsWith(name.toLowerCase()));

  const missingCast = VOICE_LINES.filter((l) => !CAST[l.name]).map((l) => l.name);
  if (missingCast.length) throw new Error(`no casting for ${missingCast.join(", ")}`);
  for (const l of VOICE_LINES) {
    const v = byName(CAST[l.name].voice);
    if (!v) throw new Error(`voice ${CAST[l.name].voice} is not on this account`);
  }
  if (castOnly) {
    console.log(`model: ${model}`);
    for (const l of VOICE_LINES) {
      const c = CAST[l.name];
      console.log(`${l.name.padEnd(18)} ${byName(c.voice)?.name?.padEnd(40)} ${c.tags} ${c.text ?? l.text}`);
    }
    return;
  }

  mkdirSync(OUT, { recursive: true });
  for (const l of VOICE_LINES) {
    const file = join(OUT, `${l.name}.mp3`);
    if (named.length ? !named.includes(l.name) : existsSync(file)) continue;
    const c = CAST[l.name];
    const voice = byName(c.voice)!;
    const text = `${c.tags} ${c.text ?? l.text}`;
    const stream = await client.textToSpeech.convert(voice.voiceId, {
      text,
      modelId: model,
      outputFormat: "mp3_44100_128",
      seed: seedOf(l.name),
      voiceSettings: { stability: c.stability ?? 0.35, similarityBoost: 0.8 },
    });
    const chunks: Uint8Array[] = [];
    for await (const chunk of stream) chunks.push(chunk);
    writeFileSync(file, Buffer.concat(chunks));
    console.log(`saved ${l.name}.mp3  (${voice.name}) ${text}`);
  }
}

main().catch((e) => {
  console.error(e?.message ?? e);
  process.exit(1);
});
