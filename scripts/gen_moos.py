#!/usr/bin/env python3
"""Generate Mansikki's moo library with ElevenLabs Sound Effects (PLAN M17.1). Spends credits: run on purpose.

    uv run python scripts/gen_moos.py            # generates only clips that are missing
    uv run python scripts/gen_moos.py --force    # regenerates everything

Writes web/public/sfx/moo/<mood>-<n>.mp3, manifest.json (what the player loads) and PROVENANCE.json (prompts,
model, plan and date). The model is set explicitly: SFX v2 is still the API default but is removed on 2027-03-01.
The key comes from ELEVENLABS_API_KEY (.env.local) and is never printed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "gateway"))
OUT = REPO / "web" / "public" / "sfx" / "moo"
MODEL = "eleven_text_to_sound_v3"
TAKES = 2

# Describe the action and the setting; counts such as "moo twice" are not followed (tech-research §6).
CLIPS: dict[str, dict] = {
    "greet": {
        "duration": 2.5,
        "prompt": "A single friendly dairy cow giving one long, warm, relaxed moo in a quiet "
        "barn, recorded close up, no other animals, no music",
    },
    "happy": {
        "duration": 1.4,
        "prompt": "A content dairy cow giving one short, cheerful moo, recorded close up in "
        "a quiet farmyard, no background noise, no music",
    },
    "question": {
        "duration": 2.0,
        "prompt": "A curious dairy cow giving one moo that rises in pitch at the end, as if "
        "asking a question, recorded close up in a quiet barn, no music",
    },
    "alarmed": {
        "duration": 1.8,
        "prompt": "A startled dairy cow giving one loud, urgent, high-pitched moo, recorded "
        "close up, no other sounds, no music",
    },
    "celebrate": {
        "duration": 3.0,
        "prompt": "A delighted dairy cow giving one long, bright, triumphant moo, then a "
        "single cowbell ring, recorded close up, no music",
    },
    "chewing": {
        "duration": 6.0,
        "loop": True,
        "prompt": "A cow slowly chewing cud, soft rhythmic chewing and "
        "grinding sounds, recorded close up in a quiet barn, no mooing, no music",
    },
}


def main() -> int:
    from app.settings import Settings
    from elevenlabs import ElevenLabs
    from elevenlabs.core.api_error import ApiError

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="regenerate clips that already exist")
    args = ap.parse_args()

    s = Settings()
    client = ElevenLabs(api_key=s.elevenlabs_api_key or "proxy-injected")
    try:
        tier = client.user.subscription.get().tier
    except Exception:  # noqa: BLE001 - provenance only
        tier = "unknown"
    OUT.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, list[str]] = {}
    provenance: list[dict] = []
    for mood, spec in CLIPS.items():
        takes = 1 if spec.get("loop") else TAKES
        manifest[mood] = []
        for n in range(1, takes + 1):
            name = f"{mood}-{n}.mp3"
            path = OUT / name
            if path.exists() and not args.force:
                print(f"keep   {name}")
            else:
                for attempt in range(5):
                    try:
                        audio = client.text_to_sound_effects.convert(
                            text=spec["prompt"],
                            model_id=MODEL,
                            duration_seconds=spec["duration"],
                            prompt_influence=0.6,
                            loop=bool(spec.get("loop")),
                            output_format="mp3_44100_128",
                        )
                        path.write_bytes(b"".join(audio))
                        break
                    except ApiError as e:
                        if e.status_code == 429 and attempt < 4:  # SFX concurrency limit
                            time.sleep(2**attempt)
                            continue
                        raise
                print(f"made   {name} ({path.stat().st_size // 1024} KB)")
            manifest[mood].append(f"/sfx/moo/{name}")
            provenance.append(
                {
                    "file": name,
                    "mood": mood,
                    "prompt": spec["prompt"],
                    "model_id": MODEL,
                    "duration_seconds": spec["duration"],
                    "loop": bool(spec.get("loop")),
                    "prompt_influence": 0.6,
                }
            )
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (OUT / "PROVENANCE.json").write_text(
        json.dumps(
            {
                "source": "ElevenLabs Sound Effects API (text to sound effects)",
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "plan": tier,
                "licence": "Generated on a paid ElevenLabs plan, which includes a commercial licence; "
                "ElevenLabs watermarks generated audio.",
                "clips": provenance,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"wrote {sum(len(v) for v in manifest.values())} clips, manifest.json and PROVENANCE.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
