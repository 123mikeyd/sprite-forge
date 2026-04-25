# Sprite Forge

AI-powered sprite sheet generation with iterative user review. Genre-aware templates, per-frame analysis, smart regen.

**Now public — work in progress.**

## The Problem

Every AI sprite tool tries to generate a perfect sheet in one shot. When it fails, you regen everything. 50+ attempts to get one animation. Good frames get thrown away with the bad.

## Our Approach

1. **Generate** — Character image + game type + style → sprite sheet
2. **Analyze** — AI breaks sheet into frames, labels each one, flags issues
3. **Review** — User sees every frame with labels, picks good/bad
4. **Regen** — Only regenerate rejected frames with adjusted prompts
5. **Assemble** — Good frames → final sheet + frame data JSON

Each generation produces usable frames. You never throw away good work.

## Project Structure

```
├── templates/
│   └── fighter.json          # MUGEN-based fighter animation template
├── src/
│   ├── generator.py          # Wraps fal.ai / nano-banana for generation
│   ├── analyzer.py           # Frame splitting + quality analysis
│   ├── reviewer.py           # Presents frames to user, collects feedback
│   ├── regenerator.py        # Regens bad frames only
│   └── assembler.py          # Good frames → final sheet + frame_data.json
├── sandbox/
│   └── preview.html          # HTML5 canvas to test animations live
├── output/                   # Generated sheets, frames, exports
└── config.yaml               # API keys, sprite size defaults
```

## Templates

Genre templates define what animations a game type needs. Based on MUGEN state numbering.

- **fighter.json** — Complete 2D fighter (movement, attacks, specials, reactions)
- **platformer.json** — Coming soon
- **rpg.json** — Coming soon

Each template includes:
- State ID (MUGEN numbering for fighters)
- Recommended frame counts
- Pre-written generation prompts
- Common issues to detect
- Frame data (startup, active, recovery)
- Hit/hurtbox flags

## Status

**Early development.** Template system designed. Analyzer and review pipeline next.

## License

TBD — private until public release.
