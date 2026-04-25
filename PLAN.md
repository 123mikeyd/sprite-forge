# Sprite Forge — 5-Phase Roadmap

**Goal:** A fully functioning, self-contained web app where you describe a character and get a game-ready sprite sheet — with per-frame review, fix tools, and multi-genre support.

---

## Phase 1: Foundation & UX Polish ✅ DONE

- Settings tab with gear icon in the top bar
- Theme system: Dark / Light / Auto (system preference)
- Game style selector framework: 2D Fighter (active), Platformer, Shmup, RPG, Beat 'em Up (all wired, disabled until Phase 4)
- Language display: English (extensible)
- Cell display size: Small / Medium / Large
- Auto-poll interval: 2s / 5s / 10s
- Background color sync between welcome page and settings
- Reset All Progress button with confirmation
- All preferences persist via localStorage
- Git cleanup: removed 30MB of generated artifacts from tracking

**What got shipped:** Settings overlay modal, CSS custom properties for theming, light-theme override rules for all major components.

---

## Phase 2: Web-Integrated Analyzer

**Problem:** Right now you can only upload pre-split frames or rely on Hermes generating exact 2x2 grids. Real sprite sheets come in all shapes.

**Work:**
- Port `src/analyzer.py` frame-detection logic to JavaScript/canvas
- Drop-zone on the UI: drag any sprite sheet PNG and auto-detect frames
- Detect transparent vs solid backgrounds automatically
- Let user override: specify grid cols/rows, or use smart auto-detect
- In-browser chroma-key and crop (no server round-trip)
- Extract frames directly into the review pipeline
- Add "Import Sheet" as a new step in the wizard

**Deliverable:** User drops a 500x500 sprite sheet and the UI shows individual frames within 2 seconds, ready for animation assignment.

---

## Phase 3: Pipeline Automation

**Problem:** The current workflow requires manually copying prompts to Hermes and waiting. It should be one command.

**Work:**
- Backend route `/api/generate_and_wait` that calls fal.ai (or other backend) and streams progress via SSE or polling
- Frontend: click "Generate" → spinner appears → image auto-appears when ready (no copy-paste)
- Auto-split uploaded/generated grids using the analyzer
- Per-frame review: mark good/bad with 1 click
- Smart regen: "Regenerate Frame 2" sends a targeted prompt that references the approved frames for consistency
- Frame locking: approved frames are pinned; only rejected ones get regened
- One-click "Build Final Sheet" from approved frames

**Deliverable:** A user can type a character description, click through 5 steps, and download a sprite sheet + JSON without ever leaving the browser tab.

---

## Phase 4: Multi-Genre Expansion

**Problem:** Only 2D Fighter templates exist. Platformer, shmup, RPG, and beat 'em up templates are stubbed in the settings but inactive.

**Work:**
- Activate each genre template in the dropdown
- Platformer: idle, run, jump, double-jump, climb, attack, hurt, die
- Shmup: ship idle, bank left, bank right, thrust, explosion, power-up glow
- RPG: walk N/S/E/W, attack, cast spell, hurt, emote, sit
- Beat 'em Up: walk, combo string (3-4 hits), grab, throw, special, getup
- Genre-specific prompt engineering: side-view for fighters, top-down or 4-dir for RPG, forward-facing for shmup
- Template-driven UI: animation inputs and default names change based on selected genre
- MUGEN state IDs for fighters, custom state numbering for other genres

**Deliverable:** Changing "Game Style" in settings reshuffles the entire wizard to show the right animations for that genre.

---

## Phase 5: Export & Engine Integration

**Problem:** The output is a PNG + JSON. Game engines need more than that.

**Work:**
- MUGEN export: generate `.cns` (constants), `.air` (animation), `.sff` reference files
- Godot export: `AnimatedSprite2D`-ready `.tres` + sprite frames + import script
- Unity export: Sprite Library Asset + Animator Controller JSON
- Hitbox/hurtbox editor: click-drag rectangles per frame, save to JSON
- Batch export: one ZIP containing sheet + JSON + engine config + README
- Export presets: "Retro" (16 colors, 64x64 cells), "HD" (256 colors, 128x128 cells), "Mobile" (small filesize, aggressive palette reduction)

**Deliverable:** User clicks "Download for Godot" and gets a `.zip` they can drag straight into a Godot project and hit Play.

---

## Current Status

| Phase | Status | Key Files |
|-------|--------|-----------|
| 1 | ✅ Complete | `app/ui.html`, `app/app.py` |
| 2 | ⏳ Next | `src/analyzer.py` (port to JS) |
| 3 | ⏳ Planned | `app/app.py` (SSE/streaming) |
| 4 | ⏳ Planned | `templates/*.json` |
| 5 | ⏳ Planned | New export modules |

**Running locally:**
```bash
cd app && python3 app.py
# Open http://localhost:5001
```

**Repo:** https://github.com/123mikeyd/sprite-forge (public, `elephant` branch has latest)
