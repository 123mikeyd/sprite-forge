#!/usr/bin/env python3
"""
Sprite Forge — single CLI entry point for the entire sprite sheet pipeline.

Subcommands:
  analyze     Detect frames + quality in a sprite sheet
  review      Generate an HTML review tool for marking frames good/bad
  normalize   Align frames to consistent groin anchor
  assemble    Build final sheet + Hermes-consumer JSON
  regen       Re-generate only bad frames from a review
  forge       Full pipeline from existing sheet (analyze → normalize → review)
  generate    Full pipeline from template (generate strips → assemble)
  import      Import a sheet + review.json → final hermes.json (no regen)

Typical workflows:

  # You have a sprite sheet, want to turn it into a game-ready asset:
  sprite-forge.py forge my_sheet.png -o output/

  # You reviewed in browser and have review.json, want final output:
  sprite-forge.py import my_sheet.png review.json -o output/

  # You want to generate a fighter from scratch:
  sprite-forge.py generate --character "red knight" --genre fighter -o output/
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Add src/ to path so we can import sibling modules
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(SCRIPT_DIR, "src")
sys.path.insert(0, SRC_DIR)


def cmd_analyze(args):
    """Run analyzer on a sprite sheet."""
    from analyzer import analyze_sheet

    sheet = args.sheet
    if not os.path.exists(sheet):
        print(f"Error: {sheet} not found")
        sys.exit(1)

    out = args.output or (os.path.splitext(sheet)[0] + "_frames.json")

    print(f"Analyzing: {sheet}")
    result = analyze_sheet(
        sheet,
        bg_mode=args.bg_mode,
        compress=args.compress,
        padding=args.padding,
        min_width=args.min_width,
        min_height=args.min_height,
    )

    with open(out, "w") as f:
        json.dump(result, f, indent=2)

    print(f"\nResults: {out}")
    print(f"  Frames: {result['total_frames']}")
    print(f"  Rows: {result['rows']}")
    print(f"  BG mode: {result['bg_mode']}")
    print(f"  Quality: {result['summary']}")
    if result.get("duplicates"):
        print(f"  Duplicates: {len(result['duplicates'])}")

    return out


def cmd_review(args):
    """Generate an HTML review tool."""
    from reviewer import generate_review_html

    analyzer_json = args.analyzer_json
    sheet = args.sheet
    out = args.output or (os.path.splitext(sheet)[0] + "_review.html")

    for p in (analyzer_json, sheet):
        if not os.path.exists(p):
            print(f"Error: {p} not found")
            sys.exit(1)

    path = generate_review_html(
        analyzer_json_path=analyzer_json,
        sheet_path=sheet,
        out_path=out,
        template_path=args.template,
    )
    print(f"Review tool: {path}")
    print(f"Open in browser, mark frames, click Export Review")
    return path


def cmd_normalize(args):
    """Normalize sprite frames to consistent anchor."""
    from analyzer import create_content_mask, find_frame_bounds, detect_bg_mode
    from normalizer import normalize_from_bounds
    from PIL import Image
    import numpy as np

    sheet = args.sheet
    if not os.path.exists(sheet):
        print(f"Error: {sheet} not found")
        sys.exit(1)

    out = args.output or (os.path.splitext(sheet)[0] + "_normalized.png")

    img = Image.open(sheet).convert("RGBA")
    arr = np.array(img)
    bg_mode = args.bg_mode
    if bg_mode == "auto":
        bg_mode = detect_bg_mode(arr)

    print(f"Normalizing: {sheet}")
    print(f"  BG mode: {bg_mode}")
    print(f"  Anchor method: {args.anchor}")
    print(f"  Target size: {args.size}x{args.size}")

    mask = create_content_mask(arr, bg_mode=bg_mode)
    bounds = find_frame_bounds(mask)
    print(f"  Detected {len(bounds)} frames")

    normalized, anchors = normalize_from_bounds(
        img, bounds,
        target_size=(args.size, args.size),
        anchor_method=args.anchor,
        bg_mode=bg_mode,
    )

    # Build output sheet
    cols = min(len(normalized), 10)
    rows_count = (len(normalized) + cols - 1) // cols
    sheet_w = cols * (args.size + 4) + 4
    sheet_h = rows_count * (args.size + 4) + 4

    result_sheet = Image.new("RGBA", (sheet_w, sheet_h), (0, 0, 0, 0))
    for i, frame in enumerate(normalized):
        col = i % cols
        row = i // cols
        x = col * (args.size + 4) + 4
        y = row * (args.size + 4) + 4
        result_sheet.paste(frame, (x, y))

    result_sheet.save(out)
    print(f"  Output: {out} ({sheet_w}x{sheet_h})")

    # Anchor stats
    xs = [a[0] for a in anchors]
    ys = [a[1] for a in anchors]
    print(f"  Anchor X spread: {max(xs)-min(xs)}px, Y spread: {max(ys)-min(ys)}px")

    return out


def cmd_assemble(args):
    """Assemble into final sheet + Hermes-consumer JSON."""
    from assembler import from_analyzer_json_by_row, from_analyzer_json

    analyzer_json = args.analyzer_json
    sheet = args.sheet
    out_json = args.output or (os.path.splitext(sheet)[0] + "_hermes.json")

    for p in (analyzer_json, sheet):
        if not os.path.exists(p):
            print(f"Error: {p} not found")
            sys.exit(1)

    if args.by_row:
        row_names = args.row_names.split(",") if args.row_names else None
        path = from_analyzer_json_by_row(
            analyzer_json_path=analyzer_json,
            sheet_path=sheet,
            out_json=out_json,
            row_names=row_names,
            default_fps=args.fps,
        )
    else:
        path = from_analyzer_json(
            analyzer_json_path=analyzer_json,
            sheet_path=sheet,
            out_json=out_json,
            fps=args.fps,
        )

    print(f"Hermes JSON: {path}")
    return path


def cmd_forge(args):
    """Full pipeline from existing sheet: analyze → normalize → review."""
    from analyzer import analyze_sheet, create_content_mask, find_frame_bounds, detect_bg_mode
    from normalizer import normalize_from_bounds
    from reviewer import generate_review_html
    from PIL import Image
    import numpy as np
    import shutil

    sheet = args.sheet
    if not os.path.exists(sheet):
        print(f"Error: {sheet} not found")
        sys.exit(1)

    out_dir = args.output or "forge_output"
    os.makedirs(out_dir, exist_ok=True)

    base_name = os.path.splitext(os.path.basename(sheet))[0]
    analyzer_out = os.path.join(out_dir, f"{base_name}_frames.json")
    normalized_out = os.path.join(out_dir, f"{base_name}_normalized.png")
    review_out = os.path.join(out_dir, f"{base_name}_review.html")

    # Copy original sheet to output dir for reference
    sheet_copy = os.path.join(out_dir, os.path.basename(sheet))
    if os.path.abspath(sheet) != os.path.abspath(sheet_copy):
        shutil.copy2(sheet, sheet_copy)

    # ── Step 1: Analyze ──
    print("=" * 60)
    print("STEP 1: Analyze")
    print("=" * 60)
    result = analyze_sheet(
        sheet,
        bg_mode=args.bg_mode,
        compress=args.compress,
        padding=args.padding,
    )
    with open(analyzer_out, "w") as f:
        json.dump(result, f, indent=2)
    print(f"  Frames: {result['total_frames']}, Rows: {result['rows']}")
    print(f"  Quality: {result['summary']}")
    print(f"  Saved: {analyzer_out}")

    # ── Step 2: Normalize ──
    print(f"\n{'=' * 60}")
    print("STEP 2: Normalize")
    print("=" * 60)
    img = Image.open(sheet).convert("RGBA")
    arr = np.array(img)
    bg_mode = result["bg_mode"]

    mask = create_content_mask(arr, bg_mode=bg_mode)
    bounds = find_frame_bounds(mask)
    print(f"  Frames: {len(bounds)}, BG: {bg_mode}, Anchor: {args.anchor}")

    normalized, anchors = normalize_from_bounds(
        img, bounds,
        target_size=(args.size, args.size),
        anchor_method=args.anchor,
        bg_mode=bg_mode,
    )

    cols = min(len(normalized), 10)
    rows_count = (len(normalized) + cols - 1) // cols
    norm_w = cols * (args.size + 4) + 4
    norm_h = rows_count * (args.size + 4) + 4
    norm_sheet = Image.new("RGBA", (norm_w, norm_h), (0, 0, 0, 0))
    for i, frame in enumerate(normalized):
        col = i % cols
        row = i // cols
        x = col * (args.size + 4) + 4
        y = row * (args.size + 4) + 4
        norm_sheet.paste(frame, (x, y))
    norm_sheet.save(normalized_out)
    xs = [a[0] for a in anchors]
    ys = [a[1] for a in anchors]
    print(f"  Output: {normalized_out} ({norm_w}x{norm_h})")
    print(f"  Anchor X spread: {max(xs)-min(xs)}px, Y spread: {max(ys)-min(ys)}px")

    # ── Step 3: Review ──
    print(f"\n{'=' * 60}")
    print("STEP 3: Review")
    print("=" * 60)
    generate_review_html(
        analyzer_json_path=analyzer_out,
        sheet_path=sheet,
        out_path=review_out,
        template_path=args.template,
    )
    print(f"  Review tool: {review_out}")
    print(f"  Open in browser, mark frames good/bad, export review.json")

    # ── Summary ──
    print(f"\n{'=' * 60}")
    print("FORGE COMPLETE")
    print("=" * 60)
    print(f"  Output dir: {out_dir}/")
    print(f"  Analyzer:   {base_name}_frames.json")
    print(f"  Normalized: {base_name}_normalized.png")
    print(f"  Review:     {base_name}_review.html")
    print(f"\n  Next steps:")
    print(f"  1. Open {review_out} in your browser")
    print(f"  2. Mark frames good (✓) or bad (✗)")
    print(f"  3. Click 'Export Review' → downloads review.json")
    print(f"  4. Run: python3 sprite-forge.py import {sheet} review.json -o {out_dir}/final")
    print(f"  5. Or run: python3 src/regenerator.py execute review.json {sheet} --out-dir {out_dir}/regen")


def cmd_import(args):
    """Import a reviewed sheet: apply review.json → final hermes.json."""
    from assembler import write_hermes_json

    sheet = args.sheet
    review_json = args.review_json

    for p in (sheet, review_json):
        if not os.path.exists(p):
            print(f"Error: {p} not found")
            sys.exit(1)

    out_dir = args.output or "final_output"
    os.makedirs(out_dir, exist_ok=True)

    with open(review_json, "r") as f:
        review = json.load(f)

    base_name = os.path.splitext(os.path.basename(sheet))[0]
    final_sheet = os.path.join(out_dir, os.path.basename(sheet))
    final_json = os.path.join(out_dir, f"{base_name}_hermes.json")

    # Filter to only good/unmarked frames
    good_frames = [
        f for f in review.get("frames", [])
        if f.get("status") in ("good", "unmarked")
    ]

    if not good_frames:
        print("Error: no good frames in review.json")
        sys.exit(1)

    # Group frames by animation
    animations = {}
    for f in good_frames:
        anim_name = f.get("animation") or "all"
        if anim_name not in animations:
            animations[anim_name] = {
                "frames": [],
                "fps": args.fps,
                "loop": True,
            }
        animations[anim_name]["frames"].append(f["bounds"])

    # If no animation names were assigned, use a single "all" animation
    if len(animations) == 1 and "all" in animations:
        # Try to detect rows from the frames
        frames_sorted = sorted(good_frames, key=lambda f: (f["bounds"][1], f["bounds"][0]))
        animations = {"all": {
            "frames": [f["bounds"] for f in frames_sorted],
            "fps": args.fps,
            "loop": True,
        }}

    # Get image size
    from PIL import Image
    img = Image.open(sheet)
    size = list(img.size)

    # Determine bg_mode from review or default
    bg_mode = review.get("bg_mode", "transparent")

    # Copy sheet
    import shutil
    if os.path.abspath(sheet) != os.path.abspath(final_sheet):
        shutil.copy2(sheet, final_sheet)

    # Write hermes.json
    write_hermes_json(
        out_path=final_json,
        sheet_path=final_sheet,
        size=tuple(size),
        animations=animations,
        bg_mode=bg_mode,
        meta={
            "source": "reviewed_import",
            "review_input": os.path.basename(review_json),
            "total_frames": len(good_frames),
            "rejected": len([
                f for f in review.get("frames", [])
                if f.get("status") == "rejected"
            ]),
        },
    )

    print(f"Final output:")
    print(f"  Sheet: {final_sheet}")
    print(f"  JSON: {final_json}")
    print(f"  Animations: {list(animations.keys())}")
    print(f"  Frames kept: {len(good_frames)}")


def cmd_generate(args):
    """Generate a character from template."""
    from generator import generate_sheet_from_template
    from assembler import assemble_from_strips

    template = args.template
    if not os.path.exists(template):
        # Try templates/ dir
        alt = os.path.join(SCRIPT_DIR, "templates", template)
        if os.path.exists(alt):
            template = alt
        else:
            print(f"Error: template '{template}' not found")
            sys.exit(1)

    out_dir = args.output or "generated"
    character = args.character or "unnamed character"
    anim_set = args.set or "min_viable_set"
    cell_w = args.cell_w
    cell_h = args.cell_h

    print(f"Generating: {character}")
    print(f"  Template: {template}")
    print(f"  Animation set: {anim_set}")
    print(f"  Backend: {args.backend}")
    print(f"  Cell size: {cell_w}x{cell_h}")

    os.makedirs(out_dir, exist_ok=True)

    # Generate strips
    print(f"\nGenerating animation strips...")
    manifest = generate_sheet_from_template(
        template_path=template,
        out_dir=os.path.join(out_dir, "strips"),
        animation_set=anim_set,
        backend=args.backend,
        character_desc=character,
        style_desc=args.style,
        cell_w=cell_w,
        cell_h=cell_h,
    )

    successful = [s for s in manifest["strips"] if s.get("path")]
    failed = [s for s in manifest["strips"] if s.get("error")]
    print(f"  Generated: {len(successful)} strips")
    if failed:
        print(f"  Failed: {len(failed)} strips")
        for f in failed:
            print(f"    - {f['animation']}: {f['error']}")

    if not successful:
        print("Error: no strips generated successfully")
        sys.exit(1)

    # Assemble
    print(f"\nAssembling final sheet...")
    sheet_out = os.path.join(out_dir, f"{os.path.basename(out_dir)}_sheet.png")
    json_out = os.path.join(out_dir, f"{os.path.basename(out_dir)}_hermes.json")

    result = assemble_from_strips(
        generator_manifest=manifest,
        out_sheet=sheet_out,
        out_json=json_out,
        cell_w=cell_w,
        cell_h=cell_h,
    )

    print(f"\nDone!")
    print(f"  Sheet: {result['sheet']}")
    print(f"  JSON: {result['json']}")
    print(f"  Animations: {result['n_animations']}")
    print(f"  Size: {result['size'][0]}x{result['size'][1]}")


def cmd_regen(args):
    """Re-generate bad frames from a review."""
    from regenerator import load_review, build_regen_plan, execute_regen_plan

    review_json = args.review_json
    sheet = args.sheet

    for p in (review_json, sheet):
        if not os.path.exists(p):
            print(f"Error: {p} not found")
            sys.exit(1)

    out_dir = args.out_dir or "regen_output"

    review = load_review(review_json)
    plan = build_regen_plan(review)

    if plan["summary"]["rejected"] == 0:
        print("No rejected frames — nothing to regenerate.")
        sys.exit(0)

    print(f"Regenerating {plan['summary']['rejected']} frames "
          f"across {plan['summary']['animations_affected']} animations...")

    result = execute_regen_plan(
        plan=plan,
        sheet_path=sheet,
        out_dir=out_dir,
        backend=args.backend,
        character_desc=args.character,
        cell_w=args.cell_w,
        cell_h=args.cell_h,
    )

    print(f"\nDone! Merged output:")
    print(f"  Sheet: {result['merged_sheet']}")
    print(f"  JSON: {result['merged_frames_json']}")
    print(f"  Good kept: {result['good_frames_kept']}, Replaced: {result['replacements_made']}")


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="sprite-forge",
        description="Sprite Forge — AI-assisted sprite sheet pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command")

    # ── analyze ──
    p = sub.add_parser("analyze", help="Detect frames + quality in a sprite sheet")
    p.add_argument("sheet", help="Sprite sheet PNG")
    p.add_argument("-o", "--output", help="Output JSON path")
    p.add_argument("--bg-mode", default="auto",
                   choices=["auto", "green", "dark", "light", "transparent"])
    p.add_argument("--compress", type=float, default=1.0)
    p.add_argument("--padding", type=int, default=5)
    p.add_argument("--min-width", type=int, default=8)
    p.add_argument("--min-height", type=int, default=8)

    # ── review ──
    p = sub.add_parser("review", help="Generate HTML review tool")
    p.add_argument("analyzer_json", help="Analyzer JSON output")
    p.add_argument("sheet", help="Sprite sheet PNG")
    p.add_argument("-o", "--output", help="Output HTML path")
    p.add_argument("--template", help="Template JSON for common_issues hints")

    # ── normalize ──
    p = sub.add_parser("normalize", help="Align frames to consistent anchor")
    p.add_argument("sheet", help="Sprite sheet PNG")
    p.add_argument("-o", "--output", help="Output PNG path")
    p.add_argument("--size", type=int, default=96, help="Target frame size")
    p.add_argument("--anchor", default="groin",
                   choices=["groin", "silhouette", "ratio"])
    p.add_argument("--bg-mode", default="auto",
                   choices=["auto", "green", "dark", "light", "transparent"])

    # ── assemble ──
    p = sub.add_parser("assemble", help="Build final sheet + Hermes-consumer JSON")
    p.add_argument("analyzer_json", help="Analyzer JSON")
    p.add_argument("sheet", help="Sprite sheet PNG")
    p.add_argument("-o", "--output", help="Output JSON path")
    p.add_argument("--by-row", action="store_true", help="Treat each row as animation")
    p.add_argument("--row-names", help="Comma-separated animation names")
    p.add_argument("--fps", type=int, default=10)

    # ── forge (full pipeline) ──
    p = sub.add_parser("forge",
        help="Full pipeline from sheet: analyze → normalize → review")
    p.add_argument("sheet", help="Sprite sheet PNG")
    p.add_argument("-o", "--output", help="Output directory")
    p.add_argument("--bg-mode", default="auto",
                   choices=["auto", "green", "dark", "light", "transparent"])
    p.add_argument("--compress", type=float, default=1.0)
    p.add_argument("--padding", type=int, default=5)
    p.add_argument("--size", type=int, default=96, help="Target frame size")
    p.add_argument("--anchor", default="groin",
                   choices=["groin", "silhouette", "ratio"])
    p.add_argument("--template", help="Template JSON for common_issues hints")

    # ── import (reviewed → final) ──
    p = sub.add_parser("import",
        help="Apply review.json → final hermes.json")
    p.add_argument("sheet", help="Sprite sheet PNG")
    p.add_argument("review_json", help="Review JSON from HTML reviewer")
    p.add_argument("-o", "--output", help="Output directory")
    p.add_argument("--fps", type=int, default=10)

    # ── generate (from template) ──
    p = sub.add_parser("generate", help="Generate a character from template")
    p.add_argument("--character", required=True, help="Character description")
    p.add_argument("--template", default="fighter.json",
                   help="Template name or path (default: fighter.json)")
    p.add_argument("--genre", default="fighter",
                   choices=["fighter", "platformer", "shmup", "rpg"],
                   help="Game genre (selects template if --template not a path)")
    p.add_argument("-o", "--output", help="Output directory")
    p.add_argument("--set", default="min_viable_set", help="Animation set name")
    p.add_argument("--backend", default="ascii",
                   choices=["image_gen", "ascii", "fal"])
    p.add_argument("--style", default="16-bit pixel art")
    p.add_argument("--cell-w", type=int, default=96)
    p.add_argument("--cell-h", type=int, default=96)

    # ── regen ──
    p = sub.add_parser("regen", help="Re-generate bad frames from review")
    p.add_argument("review_json", help="Review JSON")
    p.add_argument("sheet", help="Original sprite sheet PNG")
    p.add_argument("--out-dir", help="Output directory")
    p.add_argument("--backend", default="ascii",
                   choices=["image_gen", "ascii", "fal"])
    p.add_argument("--character", default="", help="Character description")
    p.add_argument("--cell-w", type=int, default=96)
    p.add_argument("--cell-h", type=int, default=96)

    args = parser.parse_args()

    commands = {
        "analyze": cmd_analyze,
        "review": cmd_review,
        "normalize": cmd_normalize,
        "assemble": cmd_assemble,
        "forge": cmd_forge,
        "import": cmd_import,
        "generate": cmd_generate,
        "regen": cmd_regen,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
