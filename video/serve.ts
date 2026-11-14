/**
 * Dependency-free dev server for the joke video (Node >= 22.18 runs this TypeScript directly).
 *
 *   node video/serve.ts            → http://localhost:5180
 *
 * - serves video/ as static files;
 * - GET /events: server-sent events; the page reloads when a file under video/ changes;
 * - GET /voices: the recorded voice lines in audio/voice/ as JSON names;
 * - GET /moo/<file>.mp3: Mansikki's moo clips, straight from the web app (web/public/sfx/moo);
 * - POST /save?name=x.mp4: saves the body to ~/Downloads with a free name (x-2.mp4, x-3.mp4 …);
 *   POST /save?name=x.jpg&to=out saves to video/out/ instead (overwriting).
 */
import { createServer, type ServerResponse } from "node:http";
import { createReadStream, existsSync, mkdirSync, readdirSync, statSync, watch, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { basename, extname, join, normalize, resolve } from "node:path";

const ROOT = resolve(import.meta.dirname);
const PORT = Number(process.env.PORT ?? 5180);
const TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".md": "text/markdown; charset=utf-8",
  ".mp3": "audio/mpeg",
  ".wav": "audio/wav",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".mp4": "video/mp4",
};

const clients = new Set<ServerResponse>();
let pending: NodeJS.Timeout | null = null;
watch(ROOT, { recursive: true }, (_event, file) => {
  if (!file || file.startsWith("out") || file.includes("node_modules") || basename(file).startsWith(".")) return;
  if (pending) clearTimeout(pending);
  // A multi-file edit fires many events: wait until they settle, then reload once.
  pending = setTimeout(() => {
    for (const c of clients) c.write(`data: ${JSON.stringify({ file })}\n\n`);
  }, 250);
});

function freeName(dir: string, name: string): string {
  const ext = extname(name);
  const stem = name.slice(0, name.length - ext.length);
  let candidate = name;
  for (let i = 2; existsSync(join(dir, candidate)); i++) candidate = `${stem}-${i}${ext}`;
  return candidate;
}

createServer((req, res) => {
  const url = new URL(req.url ?? "/", `http://localhost:${PORT}`);
  if (url.pathname === "/events") {
    res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache", connection: "keep-alive" });
    res.write(": hello\n\n");
    clients.add(res);
    req.on("close", () => clients.delete(res));
    return;
  }
  if (url.pathname === "/voices") {
    const dir = join(ROOT, "audio", "voice");
    const names = existsSync(dir)
      ? readdirSync(dir).filter((f) => f.endsWith(".mp3")).map((f) => f.slice(0, -4)).sort()
      : [];
    res.writeHead(200, { "content-type": "application/json", "cache-control": "no-store" });
    res.end(JSON.stringify(names));
    return;
  }
  if (url.pathname === "/save" && req.method === "POST") {
    const name = basename(url.searchParams.get("name") ?? "joke-video.mp4").replace(/[^\w.-]/g, "_");
    const toOut = url.searchParams.get("to") === "out";
    const dir = toOut ? join(ROOT, "out") : join(homedir(), "Downloads");
    const chunks: Buffer[] = [];
    req.on("data", (c: Buffer) => chunks.push(c));
    req.on("end", () => {
      try {
        mkdirSync(dir, { recursive: true });
        const file = toOut ? name : freeName(dir, name);
        writeFileSync(join(dir, file), Buffer.concat(chunks));
        const path = join(dir, file);
        console.log(`saved ${path} (${(Buffer.concat(chunks).length / 1e6).toFixed(2)} MB)`);
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify({ path }));
      } catch (e) {
        res.writeHead(500, { "content-type": "text/plain" });
        res.end(String(e));
      }
    });
    return;
  }
  if (url.pathname.startsWith("/moo/")) {
    const file = join(ROOT, "..", "web", "public", "sfx", "moo", basename(url.pathname));
    if (!existsSync(file)) {
      res.writeHead(404).end();
      return;
    }
    res.writeHead(200, { "content-type": "audio/mpeg", "cache-control": "no-store" });
    createReadStream(file).pipe(res);
    return;
  }
  const rel = normalize(decodeURIComponent(url.pathname)).replace(/^([/\\])+/, "");
  let file = join(ROOT, rel || "index.html");
  if (!file.startsWith(ROOT)) {
    res.writeHead(403).end();
    return;
  }
  if (existsSync(file) && statSync(file).isDirectory()) file = join(file, "index.html");
  if (!existsSync(file)) {
    res.writeHead(404, { "content-type": "text/plain" }).end("not found");
    return;
  }
  res.writeHead(200, { "content-type": TYPES[extname(file)] ?? "application/octet-stream", "cache-control": "no-store" });
  createReadStream(file).pipe(res);
}).listen(PORT, () => console.log(`joke video player on http://localhost:${PORT}`));
