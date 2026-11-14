# Mansikki · "what if" joke video

A 50.8-second vertical (1080×1920, 30 fps) low-poly meme video for Junction 2026: *What if you kept asking a cow for more milk?* A MrBeast-style hook, then eight scenes where people order more and more milk from Mansikki, our AI ordering cow, until the order becomes the Milky Way. The €500 limit still holds. The plan, the memes and why they were picked are in [STORYBOARD.md](STORYBOARD.md).

Everything is made here: Three.js scenes, an original 140 BPM beat and sound effects synthesised in the browser, ElevenLabs voices, and a frame-exact MP4 export. Every frame and every sound is a function of its time, so a render is the same every time.

## Run the player

From the repo root (Node 22.18 or newer runs the TypeScript server directly):

```bash
node video/serve.ts
```

Then open http://localhost:5180 in Chrome. In the Claude desktop app, the `video` entry in `.claude/launch.json` starts the same server.

- **View menu:** the whole video or one scene. **Play** (space), **◀ ▶** step one frame (arrow keys), the scrubber, **Loop**, **Mute**, **Safe areas** (TikTok's top 160 px, bottom 420 px and right 140 px).
- The address keeps the view and its local time, for example `#view=gymbro&t=4.800`. The page reloads by itself when a file in `video/` changes, and comes back to the same frame.
- The sound is mixed when the page loads (about half a second). The picture follows the sound's clock.

## Render the MP4

Press **Render MP4 (this view)**, or in the browser console:

```js
await player.render('all')                    // ~/Downloads/joke-video-all.mp4 (free names: -2, -3 …)
await player.render('all', { saveTo: 'out' }) // video/out/joke-video-all.mp4
await player.render('gymbro')                 // one scene
```

H.264 (avc1.640028, about 12 Mbit/s) and AAC 48 kHz stereo, muxed with mp4-muxer. The whole video renders in about 15 seconds. Keep the tab in front: background tabs throttle timers.

Other console hooks: `player.frame('cake', 3.2)` shows a frame, `await player.sheet('cake')` saves a 3×3 contact sheet to `video/out/sheet-cake.jpg`, `await player.sound()` mixes again and returns the stats, `await player.voiceStats()` lists where each line starts and ends.

## Change texts, numbers and timing

| What | Where |
|---|---|
| Every text and number on screen, the header, the card counters and lines, the spoken words | `src/timeline.js` |
| Scene lengths | `beats` in `src/timeline.js` (whole beats at 140 BPM keep cuts on the beat) |
| What happens when in a scene | the `B` beats at the top of each `src/views/<scene>.js`; the `sounds()` cues in the same file use them |
| Music style and its rests | the `{ music, from, rests }` cue in each view's `sounds()`; patterns in `src/audio/score.js` |
| Sound effects | `src/audio/synth.js` (all synthesised, never sampled) |
| Levels, ducking, limiter | `src/audio/mix.js` |
| Casting and delivery tags | `voices.ts` |

After changing a beat, check `await player.voiceStats()`: no line should run past its scene (`overrun`).

## Remake the voices

The voices are committed in `audio/voice/`, so rendering needs no key. To record them you need `ELEVENLABS_API_KEY` in the git-ignored `.env.local` in the repo root (`npx -y @elevenlabs/cli@latest onboard init` writes it). Never print the file or put the key in code.

```bash
node --env-file=.env.local video/voices.ts --cast           # casting and model, records nothing
node --env-file=.env.local video/voices.ts                  # records the missing lines
node --env-file=.env.local video/voices.ts gymbro-deceive   # records the named lines again
```

Lines use the model `eleven_v4` with delivery tags (`[whispers]`, `[deadpan]`, …), stability 0.3–0.5 and similarity 0.8. Rooms (the narrator's hall) and the robot filter are added in the mix, so the recordings stay dry. The mix measures each line (20 ms RMS windows), starts it at its first word, levels its loudest 20 ms to −10 dB and dips the music to 40 % under it. If a line runs long, remake it with tighter tags (`[fast]`) or raise its `rate` in the view's `sounds()`.

## Files

```
video/
  serve.ts            dev server: static files, reload on change (SSE), GET /voices, GET /moo/*, POST /save
  index.html          the player page (Three.js and mp4-muxer from jsDelivr, pinned)
  voices.ts           ElevenLabs recording
  audio/voice/*.mp3   the recorded lines
  src/main.js         the player: frame(T), transport, sheets, console hooks
  src/timeline.js     segments, texts, numbers, voice lines
  src/export.js       WebCodecs + mp4-muxer export
  src/views/*.js      one file per scene: sounds(segment) and build(segment) → { scene, camera, update(t), overlay(g, t) }
  src/kit/            shared: seeded random, easing and keyframes, palette, materials, person, cow, robot,
                      world props, props, effects, 2D text and phone screens, galaxy, camera helpers
  src/audio/          synth.js (instruments and effects), score.js (the beat), mix.js (the offline mix)
  out/                renders and contact sheets (git-ignored)
```

Mansikki's moos are the web app's own clips (`web/public/sfx/moo`, see its `PROVENANCE.json`). Valio product names are as on valio.fi (checked 14 Nov 2026), drawn in our own lettering without the Valio logo. No copyrighted songs, characters or clips are used.
