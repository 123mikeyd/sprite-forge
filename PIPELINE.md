# Sprite Forge — Pipeline

AI-assisted sprite sheet generation with iterative user review, built
to produce assets any Hermes Agent-generated 2D game can load directly.

## The whole chain in 30 seconds

```
  [character idea]  or  [existing sheet PNG]
          │
          ▼
  sprite-forge.py forge <sheet>     ← one command, full pipeline
          │
          ├─ Step 1: analyzer.py    ← detect frames + quality
          ├─ Step 2: normalizer.py  ← align frames to groin anchor
          ├─ Step 3: reviewer.py    ← generate HTML review tool
          │
          ▼
  user opens review.html            ← mark frames good/bad, assign anims
          │
          ▼
  sprite-forge.py import <sheet> review.json  → final hermes.json
          │                    (or)
          ▼
  regenerator.py execute review.json <sheet>  → regen bad, keep good
          │
          ▼
  hermes.json (v1)                  ← Hermes-consumer format
          │
          ▼
  any Hermes game                   ← ~60 lines of JS loads and animates
```

## Quick start — from a sheet you already have

```bash
# ONE COMMAND does everything:
python3 sprite-forge.py forge my_fighter.png -o output/

# This runs: analyze → normalize → review
# Open output/my_fighter_review.html in your browser
# Mark frames good/bad, click "Export Review" → downloads review.json

# Then produce the final game-ready asset:
python3 sprite-forge.py import my_fighter.png review.json -o output/final/

# OR regenerate bad frames first, then assemble:
python3 src/regenerator.py execute review.json my_fighter.png \
    --out-dir output/regen/ --backend ascii --character "my fighter"
```

## Quick start — generate a new character from scratch

```bash
# Generate a fighter using ASCII backend (free, retro aesthetic):
python3 sprite-forge.py generate \
    --character "red armored knight" \
    --template templates/fighter.json \
    --set min_viable_set \
    --backend ascii \
    -o output/red_knight/

# Or a platformer character:
python3 sprite-forge.py generate \
    --character "forest elf archer" \
    --template templates/platformer.json \
    --set min_viable_set \
    --backend ascii \
    -o output/elf_archer/

# Or a shmup ship:
python3 sprite-forge.py generate \
    --character "golden starfighter" \
    --template templates/shmup.json \
    --set min_viable_set \
    --backend ascii \
    -o output/starfighter/
```

## CLI reference

```
sprite-forge.py <command> [options]

Commands:
  analyze <sheet>              Detect frames + quality in a sprite sheet
  review <analyzer.json> <sheet>  Generate HTML review tool
  normalize <sheet>            Align frames to consistent anchor point
  assemble <analyzer.json> <sheet>  Build final sheet + Hermes JSON
  forge <sheet>                Full pipeline: analyze → normalize → review
  import <sheet> <review.json>  Apply review → final hermes.json
  generate --character <desc>  Generate from template (fighter/platformer/shmup)
  regen <review.json> <sheet>  Re-generate only bad frames
```

## ASCII mode — when you just want to see it work

No API calls, no image generator. Makes retro terminal-green sprites
for testing the pipeline:

```bash
python3 src/generator.py strip \
    --animation "idle" \
    --out /tmp/idle_strip.png \
    --backend ascii \
    --frames 4 \
    --character "CAT"
```

## The Hermes-consumer JSON format (v1)

```json
{
  "version": 1,
  "sheet": "cat_fighter.png",
  "size": [500, 500],
  "bg_mode": "transparent",
  "animations": {
    "idle": { "frames": [[10, 10, 32, 29], ...], "fps": 6, "loop": true },
    "walk": { "frames": [...], "fps": 10, "loop": true },
    "punch": {
      "frames": [...],
      "fps": 15,
      "loop": false,
      "frame_data": { "startup": 3, "active": 2, "recovery": 5 },
      "state_id": 200
    }
  },
  "meta": { "source": "analyzer_json_by_row", "total_frames": 61, "rows": 6 }
}
```

Each animation:
- `frames`: list of `[x, y, w, h]` source-rectangle arrays.
- `fps`: recommended playback rate.
- `loop`: whether the animation repeats.
- `frame_data` (optional, fighters): startup/active/recovery frame counts.
- `state_id` (optional, MUGEN): standard MUGEN state number (200=LP, 400=cLP, etc.).

## Consumer example (in any Hermes game)

See `sandbox/demo_game.html` for a complete ~60-line runtime. The core is:

```javascript
const descriptor = await (await fetch('hermes.json')).json();
const sheet = await loadImage(descriptor.sheet);

// Pick an animation + frame
const anim = descriptor.animations['idle'];
const [sx, sy, sw, sh] = anim.frames[frameIndex];
ctx.drawImage(sheet, sx, sy, sw, sh, dx, dy, sw * scale, sh * scale);
```

Advance `frameIndex` at `1000 / anim.fps` ms per step, wrap or clamp
based on `anim.loop`. That's it.

## Preview tools

- `sandbox/preview.html` — interactive frame grid + flipbook
- `sandbox/curator.html` — browser UI for grouping frames into named animations
- `sandbox/demo_game.html` — ~60-line consumer demo
- `sandbox/training_dummy.html` — SF2-style input system + frame data display

## The reviewer (NEW)

`src/reviewer.py` generates a self-contained HTML file. Open it in a browser:

- See every frame cropped from the sheet with quality metrics
- Click to select frames, Shift+Click to multi-select
- Press **G** to mark good, **B** to mark bad
- For bad frames, pick from pre-populated causes (cropped, blurry, wrong anim, etc.)
- Assign animation names per row
- Click "Export Review" → downloads `review.json`

The reviewer embeds the sheet image as base64, so it works offline —
just open the HTML file directly. No server needed.

## The regenerator (NEW)

`src/regenerator.py` consumes `review.json` and keeps good frames while
regenerating only the rejected ones. Two modes:

```bash
# Plan mode: see what would be regenerated (dry run)
python3 src/regenerator.py plan review.json -o regen_plan.json

# Execute mode: generate replacement strips, merge good + new
python3 src/regenerator.py execute review.json sheet.png \
    --out-dir regen_output/ --backend ascii --character "CAT"
```

Strategy: group rejected frames by animation → generate a fresh strip per
animation → detect frames in new strip → map new frames onto old positions
→ composite. Good frames from the original are untouched.

## Genre templates

| Template | File | States | Animations |
|----------|------|--------|------------|
| 2D Fighter | `templates/fighter.json` | 32+ MUGEN states | idle, walk, 6 attack types, crouch, jump, block, specials, supers |
| Platformer | `templates/platformer.json` | 12 states | idle, walk, jump rise/peak/fall/land, light/heavy attack, hurt, death, climb, push |
| Shmup | `templates/shmup.json` | 12 states | idle, bank L/R/up/down, shoot, special, projectile, hit, death, respawn, powerup |

Each template defines:
- `animation_sets` — min_viable_set (7-12 anims), standard_set, full_set
- Per-state frame counts, prompts, common_issues, frame_data
- Timing defaults (FPS per animation type)

## Legal / licensing

- **Test sprites:** `test_sprites/cat_fighter.png` is CC-BY 3.0 by
  Umplix (edit of dogchicken's original). See `test_sprites/ATTRIBUTION.md`.
  The test sprite is used for analyzer regression testing ONLY — it is
  not part of Sprite Forge proper and should not be redistributed with
  derivative games without honoring the CC-BY attribution.
- **Your generated sprites:** whatever rights your chosen backend
  grants. `image_gen` inherits the rights of the image generator you
  pass in. `ascii` mode produces novel output with no training data
  concerns (pyfiglet is MIT, your glyphs are derived deterministically).
- **Never train or test Sprite Forge on sprites ripped from commercial
  games.** Capcom, SNK, Midway, Arc System Works all actively enforce
  copyright on their sprite art. Stick to OpenGameArt, Kenney.nl,
  itch.io free packs, or your own generations.

## What's in the repo

```
sprite-forge/
├── sprite-forge.py               ← MAIN CLI — single entry point
├── README.md                     overview + vision
├── PIPELINE.md                   this file — end-to-end instructions
├── config.example.yaml           API keys config (only needed for fal backend)
├── templates/
│   ├── fighter.json              MUGEN-based 32+-state fighter template
│   ├── platformer.json           platformer 12-state template (NEW)
│   └── shmup.json                shmup 12-state template (NEW)
├── src/
│   ├── analyzer.py               frame detection + quality analysis (658 lines)
│   ├── generator.py              3-backend strip generator (434 lines)
│   ├── assembler.py              strip stitcher + Hermes JSON writer (331 lines)
│   ├── normalizer.py             groin-anchor frame alignment (681 lines) (NEW)
│   ├── reviewer.py               HTML review tool generator (NEW)
│   └── regenerator.py            keep-good/regen-bad pipeline (NEW)
├── sandbox/
│   ├── preview.html              interactive frame grid + flipbook
│   ├── curator.html              animation grouping UI
│   ├── demo_game.html            ~60-line consumer demo
│   └── training_dummy.html       SF2-style input system
└── test_sprites/
    ├── ATTRIBUTION.md            CC-BY credits
    └── cat_fighter.png           test corpus (not redistributed)
```

## Verified to work

- **`sprite-forge.py forge`** — full pipeline on cat_fighter: 61 frames
  detected (60 good, 1 sparse), normalized to groin anchor (X spread 20px,
  Y spread 10px), HTML review tool generated.
- **`sprite-forge.py assemble --by-row`** — produces valid Hermes JSON
  with 6 named animations.
- **`sprite-forge.py generate`** — generates 7 animation strips from
  platformer template via ASCII backend, assembles into 626x732 sheet
  + hermes.json.
- **`src/regenerator.py plan`** — correctly identifies rejected frames
  from review.json and groups them by animation with fix instructions.
- **`sandbox/demo_game.html`** — loads the JSON, animates in browser,
  HUD shows live frame counter.
- **`src/normalizer.py`** — groin anchor method: 6px X spread, 3px Y
  spread on 10-frame Ares test (best of 3 methods tested).
