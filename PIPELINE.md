# Sprite Forge — Pipeline

AI-assisted sprite sheet generation with iterative user review, built
to produce assets any Hermes Agent-generated 2D game can load directly.

## The whole chain in 30 seconds

```
  [character idea]  or  [existing sheet PNG]
          │
          ▼
  src/generator.py        ← create per-animation strips
    - backend: image_gen  (caller's image tool)
    - backend: ascii      (local pyfiglet, retro, no API)
    - backend: fal        (stub until credits added)
          │
          ▼
  src/analyzer.py         ← detect frames + quality per strip or sheet
          │
          ▼
  src/assembler.py        ← stitch strips OR re-export analyzer JSON
          │
          ▼
  hermes.json (v1)        ← Hermes-consumer format
          │
          ▼
  any Hermes game         ← ~60 lines of JS loads and animates
```

## Quick start — from a sheet you already have

```bash
# 1. Analyze: find frames, detect background, emit analyzer.json
python3 src/analyzer.py path/to/sheet.png -o sheet_frames.json

# 2. Publish as Hermes-consumer JSON (one animation per detected row)
python3 src/assembler.py from-analyzer \
    --analyzer-json sheet_frames.json \
    --sheet path/to/sheet.png \
    --out sheet_hermes.json \
    --by-row \
    --row-names idle walk run punch kick stand

# 3. Drop both PNG and sheet_hermes.json in your game's assets/.
#    Copy sandbox/demo_game.html's <script> block into your game.
#    Done.
```

## Quick start — generate a new character from scratch

```python
from generator import generate_sheet_from_template

# You pass an image-generation callable. Hermes's built-in
# `image_generate` tool satisfies the contract:
#   (prompt: str, **kwargs) -> path_to_generated_png

def my_gen(prompt, aspect_ratio='landscape'):
    return hermes_image_generate(prompt=prompt, aspect_ratio=aspect_ratio)

manifest = generate_sheet_from_template(
    template_path='templates/fighter.json',
    out_dir='generated/nova_fighter',
    animation_set='min_viable_set',  # 21 states, ~80-120 frames
    backend='image_gen',
    image_gen_callable=my_gen,
    character_desc='Nova, dark-haired anime girl in neon-blue club attire',
    style_desc='crisp 2D sprite art, saturated colors, clean silhouette',
    cell_w=96,
    cell_h=96,
)

# Then assemble all the strips into one sheet + Hermes JSON
from assembler import assemble_from_strips
result = assemble_from_strips(
    generator_manifest=manifest,
    out_sheet='generated/nova_fighter/sheet.png',
    out_json='generated/nova_fighter/hermes.json',
)
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

The strip writes out a PNG with pyfiglet-rendered glyphs on a bright-
green chroma-key background, ready for analyzer.

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

## Preview tool

`sandbox/preview.html` loads a sheet + analyzer JSON and shows every
detected frame in a clickable grid. Shift-click multiple frames, hit
"Play selection" to flipbook-animate any subset. Also includes row
preset buttons that select whole rows as candidate animations.

Useful for:
- Visual verification after running analyzer
- Finding bad splits or missed frames before publishing
- Testing flipbook timing at different FPS
- Picking out the exact frame range that belongs to one animation

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
├── README.md                     overview + vision
├── PIPELINE.md                   this file — end-to-end instructions
├── config.example.yaml           API keys config (only needed for fal backend)
├── templates/
│   └── fighter.json              MUGEN-based 32+-state fighter template
├── src/
│   ├── analyzer.py               frame detection + quality analysis (606 lines)
│   ├── generator.py              3-backend strip generator
│   └── assembler.py              strip stitcher + Hermes JSON writer
├── sandbox/
│   ├── preview.html              interactive frame grid + flipbook
│   └── demo_game.html            ~60-line consumer demo
└── test_sprites/
    ├── ATTRIBUTION.md            CC-BY credits
    └── cat_fighter.png           test corpus (not redistributed)
```

## Known gaps (pipeline is NOT yet complete)

Things this commit does NOT ship:
- `reviewer.py` — user-feedback UI for marking frames good/bad
- `regenerator.py` — regens only the rejected frames, keeping good ones
- Platformer / RPG / shmup templates (only `fighter.json` exists)
- Real `fal.ai` backend (stub raises NotImplementedError)
- Skill entry for other Hermes instances (`consumer.md` in `skills/` —
  drafted separately)

## Verified to work (on branch `build-pipeline`)

- **analyzer.py:** bug-fixed transparent-bg detection; finds 61/61
  sprites on the CC-BY cat_fighter test sheet (was 25/61 before fix)
- **assembler.py from-analyzer --by-row:** produces valid Hermes JSON
  with 6 named animations
- **sandbox/demo_game.html:** loads the JSON, animates in browser,
  HUD shows live frame counter
- **Full chain end-to-end tested in a headless browser:** all 6 anims
  play, character renders correctly, walk counter advances
