#!/usr/bin/env python3
"""
Sprite Forge Regenerator — re-gen only bad frames, keep good ones.

The core differentiator: never throw away good work. When the user marks
frames as bad in the reviewer, this module creates a targeted regeneration
plan and (optionally) executes it by generating replacement strips and
extracting only the needed frames.

Usage:
    # Just create the plan (dry run)
    python3 src/regenerator.py plan review.json -o regen_plan.json

    # Execute: generate replacements + merge
    python3 src/regenerator.py execute review.json sheet.png \\
        --out-dir regen_output/ --backend ascii --character "CAT"

The regeneration strategy:
  1. Group rejected frames by animation (row name or assigned anim)
  2. For each animation with rejected frames, generate a fresh strip
  3. Detect frames in the new strip via analyzer
  4. Map new frames onto old frame positions (by index within animation)
  5. Composite: keep good old frames, paste in new replacements
  6. Output a new analyzer.json + keyed sheet ready for assembler
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image
import numpy as np

# Import from sibling modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyzer import analyze_sheet, create_content_mask, find_frame_bounds
from normalizer import normalize_animation_frames


def load_review(review_path: str) -> Dict:
    """Load a review.json produced by the HTML reviewer."""
    with open(review_path, "r") as f:
        return json.load(f)


def build_regen_plan(review: Dict) -> Dict:
    """Analyze a review and produce a regeneration plan.

    Returns a dict with:
      - keep: frames that passed review
      - reject: frames that need replacement, grouped by animation
      - plan: per-animation regeneration instructions
    """
    frames = review.get("frames", [])
    keep = []
    reject_by_anim: Dict[str, List[Dict]] = {}

    for f in frames:
        status = f.get("status", "unmarked")
        if status == "good":
            keep.append(f)
        elif status == "rejected":
            anim = f.get("animation") or f"row_unknown"
            if anim not in reject_by_anim:
                reject_by_anim[anim] = []
            reject_by_anim[anim].append(f)
        # "unmarked" frames are kept by default (user didn't reject them)
        elif status == "unmarked":
            keep.append(f)

    # Build plan
    plan_entries = []
    for anim, rejected in reject_by_anim.items():
        # Collect causes across all rejected frames for this animation
        all_causes = []
        for r in rejected:
            all_causes.extend(r.get("causes", []))
        unique_causes = list(dict.fromkeys(all_causes))  # dedupe, preserve order

        # Build a prompt hint from causes
        fix_instructions = _causes_to_instructions(unique_causes)

        plan_entries.append({
            "animation": anim,
            "rejected_indices": [r["index"] for r in rejected],
            "rejected_count": len(rejected),
            "causes": unique_causes,
            "fix_instructions": fix_instructions,
            "notes": [r.get("notes", "") for r in rejected if r.get("notes")],
        })

    return {
        "sheet_path": review.get("sheet_path"),
        "analyzer_input": review.get("analyzer_input"),
        "review_timestamp": review.get("timestamp"),
        "summary": {
            "total_frames": len(frames),
            "kept": len(keep),
            "rejected": sum(len(v) for v in reject_by_anim.values()),
            "animations_affected": len(plan_entries),
        },
        "keep": keep,
        "reject_by_anim": {k: v for k, v in reject_by_anim.items()},
        "plan": plan_entries,
    }


def _causes_to_instructions(causes: List[str]) -> str:
    """Convert reviewer causes into generation fix instructions."""
    fixes = []
    for cause in causes:
        if cause in ("cropped_off", "merged_sprites"):
            fixes.append("character must be FULLY CONTAINED within each cell, no cropping at edges")
        elif cause in ("blurry_low_res",):
            fixes.append("crisp pixel art, sharp edges, no anti-aliasing or blur")
        elif cause in ("wrong_animation", "missing_frame"):
            fixes.append("ensure the animation motion is clearly distinct between frames")
        elif cause in ("duplicate_frame",):
            fixes.append("each frame must show a DIFFERENT pose in the animation sequence")
        elif cause in ("extra_noise_artifacts",):
            fixes.append("clean sprite art, no stray pixels, noise, or artifacts outside character")
        elif cause in ("background_bleed",):
            fixes.append("solid chroma-key background, no color bleeding into sprite edges")
        elif cause in ("inconsistent_size",):
            fixes.append("character must be the SAME size in every frame, centered consistently")
        elif cause in ("wrong_color_palette",):
            fixes.append("consistent color palette across all frames, matching character design")
        elif cause in ("empty_frame",):
            fixes.append("character must be visible and have substantial content in every frame")
        else:
            fixes.append(cause.replace("_", " "))
    return "; ".join(fixes) if fixes else "improve overall quality and consistency"


def execute_regen_plan(
    plan: Dict,
    sheet_path: str,
    out_dir: str,
    backend: str = "ascii",
    image_gen_callable=None,
    character_desc: str = "",
    style_desc: str = "16-bit pixel art",
    cell_w: int = 96,
    cell_h: int = 96,
) -> Dict:
    """Execute a regeneration plan: generate replacement strips, extract
    good frames, merge into a new sheet.

    For each animation with rejected frames:
      1. Generate a fresh strip for that animation
      2. Detect frames in the new strip
      3. Map new frames to old frame indices
      4. Replace the bad frames with new ones

    Returns a dict with the new sheet path and updated frame data.
    """
    from generator import generate_strip

    os.makedirs(out_dir, exist_ok=True)
    keep_frames = plan.get("keep", [])
    reject_by_anim = plan.get("reject_by_anim", {})

    # Load original sheet
    original_sheet = Image.open(sheet_path).convert("RGBA")

    # Build a mapping of good frames we'll keep from the original
    good_frame_map = {}  # index -> bounds
    for f in keep_frames:
        good_frame_map[f["index"]] = f["bounds"]

    # For each animation needing regen, generate a new strip
    replacement_frames = {}  # index -> (x, y, w, h) in final sheet
    new_strip_paths = []

    for anim_name, rejected_frames in reject_by_anim.items():
        n_rejected = len(rejected_frames)
        # We generate a strip with at least as many frames as the original
        # animation had (rejected + kept), so we can re-map
        # For simplicity, generate n_rejected * 2 frames to have options
        gen_frames = max(n_rejected * 2, 4)

        safe_name = "".join(c if c.isalnum() else "_" for c in anim_name)
        strip_path = os.path.join(out_dir, f"regen_{safe_name}.png")

        # Build enhanced prompt with fix instructions
        fix = "; ".join(
            p.get("fix_instructions", "")
            for p in plan.get("plan", [])
            if p["animation"] == anim_name
        )

        try:
            generate_strip(
                animation=anim_name,
                out_path=strip_path,
                n_frames=gen_frames,
                cell_w=cell_w,
                cell_h=cell_h,
                character_desc=character_desc,
                style_desc=style_desc,
                backend=backend,
                image_gen_callable=image_gen_callable,
                extra_instructions=fix,
            )
            new_strip_paths.append(strip_path)
        except Exception as e:
            print(f"  WARNING: Failed to generate strip for '{anim_name}': {e}")
            continue

        # Detect frames in the new strip
        try:
            result = analyze_sheet(strip_path, bg_mode="auto")
            new_frames = [
                fr["bounds"] if isinstance(fr, dict) else fr
                for fr in result.get("frames", [])
            ]
        except Exception as e:
            print(f"  WARNING: Failed to analyze new strip for '{anim_name}': {e}")
            continue

        if not new_frames:
            print(f"  WARNING: No frames detected in new strip for '{anim_name}'")
            continue

        # Map new frames to old frame indices
        # Strategy: assign new frames sequentially to rejected positions
        new_strip_img = Image.open(strip_path).convert("RGBA")
        for i, rejected in enumerate(rejected_frames):
            if i < len(new_frames):
                # Crop from new strip
                bx = new_frames[i]
                if isinstance(bx, dict):
                    bx = bx["bounds"]
                x, y, w, h = bx
                crop = new_strip_img.crop((x, y, x + w, y + h))
                replacement_frames[rejected["index"]] = {
                    "image": crop,
                    "original_bounds": rejected["bounds"],
                }

    # Now rebuild the sheet: keep good frames from original, paste in replacements
    # Strategy: create a new sheet of the same size, draw original frames,
    # overlay replacements
    final_sheet = original_sheet.copy()

    for idx, repl in replacement_frames.items():
        orig_bounds = repl["original_bounds"]
        x, y, w, h = orig_bounds
        new_img = repl["image"]
        # Resize replacement to match original frame size
        new_resized = new_img.resize((w, h), Image.NEAREST)
        # Paste into the sheet at the original position
        final_sheet.paste(new_resized, (x, y), new_resized)

    # Save the merged sheet
    merged_path = os.path.join(out_dir, "merged_sheet.png")
    final_sheet.save(merged_path)

    # Build updated frame data (same bounds, but mark replaced frames)
    updated_frames = []
    for f in keep_frames + [
        {
            "index": idx,
            "bounds": repl["original_bounds"],
            "quality": "good",
            "status": "replaced",
        }
        for idx, repl in replacement_frames.items()
    ]:
        updated_frames.append(f)
    updated_frames.sort(key=lambda f: f["index"])

    # Write updated analyzer-compatible JSON
    updated_json_path = os.path.join(out_dir, "merged_frames.json")
    updated_data = {
        "image_path": merged_path,
        "current_size": list(final_sheet.size),
        "bg_mode": "transparent",
        "total_frames": len(updated_frames),
        "frames": [
            {
                "bounds": f["bounds"],
                "quality": f.get("quality", "good"),
                "index": f["index"],
            }
            for f in updated_frames
        ],
        "regenerated": True,
        "replacements_made": len(replacement_frames),
    }
    with open(updated_json_path, "w") as f:
        json.dump(updated_data, f, indent=2)

    return {
        "merged_sheet": merged_path,
        "merged_frames_json": updated_json_path,
        "replacements_made": len(replacement_frames),
        "new_strip_paths": new_strip_paths,
        "good_frames_kept": len(keep_frames),
        "total_frames": len(updated_frames),
    }


# ── CLI ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Sprite Forge Regenerator — re-gen bad frames only"
    )
    sub = parser.add_subparsers(dest="cmd")

    # Plan subcommand
    p_plan = sub.add_parser("plan", help="Create a regeneration plan from review.json")
    p_plan.add_argument("review_json", help="Path to review.json from the HTML reviewer")
    p_plan.add_argument("-o", "--output", default="regen_plan.json",
                        help="Output plan path")

    # Execute subcommand
    p_exec = sub.add_parser("execute", help="Execute a regeneration plan")
    p_exec.add_argument("review_json", help="Path to review.json")
    p_exec.add_argument("sheet", help="Original sprite sheet PNG")
    p_exec.add_argument("--out-dir", required=True, help="Output directory")
    p_exec.add_argument("--backend", default="ascii",
                        choices=["image_gen", "ascii", "fal"])
    p_exec.add_argument("--character", default="", help="Character description")
    p_exec.add_argument("--cell-w", type=int, default=96)
    p_exec.add_argument("--cell-h", type=int, default=96)

    args = parser.parse_args()

    if args.cmd == "plan":
        review = load_review(args.review_json)
        plan = build_regen_plan(review)

        with open(args.output, "w") as f:
            json.dump(plan, f, indent=2)

        s = plan["summary"]
        print(f"Regen plan: {args.output}")
        print(f"  Total: {s['total_frames']} frames")
        print(f"  Keep: {s['kept']} frames")
        print(f"  Reject: {s['rejected']} frames across {s['animations_affected']} animations")
        for entry in plan["plan"]:
            print(f"  - {entry['animation']}: {entry['rejected_count']} frames to regen")
            print(f"    Causes: {', '.join(entry['causes'])}")
            print(f"    Fix: {entry['fix_instructions']}")

    elif args.cmd == "execute":
        review = load_review(args.review_json)
        plan = build_regen_plan(review)

        if plan["summary"]["rejected"] == 0:
            print("No rejected frames in review — nothing to regenerate.")
            sys.exit(0)

        print(f"Regenerating {plan['summary']['rejected']} frames "
              f"across {plan['summary']['animations_affected']} animations...")

        result = execute_regen_plan(
            plan=plan,
            sheet_path=args.sheet,
            out_dir=args.out_dir,
            backend=args.backend,
            character_desc=args.character,
            cell_w=args.cell_w,
            cell_h=args.cell_h,
        )

        print(f"\nDone! Merged output:")
        print(f"  Sheet: {result['merged_sheet']}")
        print(f"  Frames JSON: {result['merged_frames_json']}")
        print(f"  Good frames kept: {result['good_frames_kept']}")
        print(f"  Replacements made: {result['replacements_made']}")
        print(f"  Total frames: {result['total_frames']}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
