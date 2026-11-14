/**
 * Frame-exact MP4 export with WebCodecs: H.264 video (avc1.640028, about 12 Mbit/s) and AAC audio
 * (mp4a.40.2, 192 kbit/s; Opus if AAC is missing), muxed with mp4-muxer. Each frame is drawn at its exact
 * time; the audio is the same buffer the preview plays. The file is posted to the dev server, which saves
 * it in ~/Downloads (or video/out/ with saveTo: 'out').
 */
import { ArrayBufferTarget, Muxer } from "mp4-muxer";
import { FPS, H, W } from "./timeline.js";

const VIDEO = { codec: "avc1.640028", width: W, height: H, bitrate: 12_000_000, framerate: FPS };

async function audioConfig(sampleRate) {
  for (const codec of ["mp4a.40.2", "opus"]) {
    const config = { codec, sampleRate, numberOfChannels: 2, bitrate: 192_000 };
    try {
      if ((await AudioEncoder.isConfigSupported(config)).supported) return config;
    } catch {
      /* try the next */
    }
  }
  return null;
}

export async function exportMp4({ from, to, drawFrame, canvas, audio, name, saveTo = null, onProgress = () => {} }) {
  if (!(await VideoEncoder.isConfigSupported(VIDEO)).supported) throw new Error("H.264 encoding is not supported here");
  const sampleRate = audio?.sampleRate ?? 48000;
  const aConfig = audio ? await audioConfig(sampleRate) : null;
  const muxer = new Muxer({
    target: new ArrayBufferTarget(),
    video: { codec: "avc", width: W, height: H, frameRate: FPS },
    audio: aConfig ? { codec: aConfig.codec === "opus" ? "opus" : "aac", numberOfChannels: 2, sampleRate } : undefined,
    fastStart: "in-memory",
    firstTimestampBehavior: "offset", // AAC adds priming samples
  });

  let failure = null;
  const venc = new VideoEncoder({ output: (chunk, meta) => muxer.addVideoChunk(chunk, meta), error: (e) => (failure = e) });
  venc.configure(VIDEO);
  const frames = Math.round((to - from) * FPS);
  for (let i = 0; i < frames; i++) {
    if (failure) throw failure;
    drawFrame(from + i / FPS);
    const vf = new VideoFrame(canvas, { timestamp: Math.round((i * 1e6) / FPS), duration: Math.round(1e6 / FPS) });
    venc.encode(vf, { keyFrame: i % (FPS * 2) === 0 });
    vf.close();
    if (venc.encodeQueueSize > 6) await new Promise((r) => venc.addEventListener("dequeue", r, { once: true }));
    if (i % 15 === 0) {
      onProgress(i / frames);
      await new Promise((r) => setTimeout(r, 0));
    }
  }
  await venc.flush();

  if (aConfig) {
    const aenc = new AudioEncoder({ output: (chunk, meta) => muxer.addAudioChunk(chunk, meta), error: (e) => (failure = e) });
    aenc.configure(aConfig);
    const start = Math.round(from * sampleRate);
    const total = Math.round((to - from) * sampleRate);
    const L = audio.getChannelData(0);
    const R = audio.numberOfChannels > 1 ? audio.getChannelData(1) : L;
    const block = 4096;
    for (let off = 0; off < total; off += block) {
      const n = Math.min(block, total - off);
      const data = new Float32Array(n * 2);
      for (let k = 0; k < n; k++) {
        const idx = start + off + k;
        data[k] = idx < L.length ? L[idx] : 0;
        data[n + k] = idx < R.length ? R[idx] : 0;
      }
      const ad = new AudioData({ format: "f32-planar", sampleRate, numberOfFrames: n, numberOfChannels: 2, timestamp: Math.round((off * 1e6) / sampleRate), data });
      aenc.encode(ad);
      ad.close();
    }
    await aenc.flush();
  }
  if (failure) throw failure;
  muxer.finalize();
  onProgress(1);
  const body = new Blob([muxer.target.buffer], { type: "video/mp4" });
  const q = new URLSearchParams({ name });
  if (saveTo === "out") q.set("to", "out");
  const res = await fetch(`/save?${q}`, { method: "POST", body });
  if (!res.ok) throw new Error(`save failed: ${await res.text()}`);
  return (await res.json()).path;
}
