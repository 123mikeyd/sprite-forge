#!/usr/bin/env python3
"""
Sprite Forge Normalizer — align sprite frames to a consistent anchor point.

The #1 problem with AI-generated sprite sheets: each frame has the character
at a slightly different position. When played as animation, the character
"jumps" around because there's no consistent anchor.

This module finds the WAIST/GROIN anchor point in each frame and aligns
all frames so that point is at the same (x, y) coordinate. The waist is
the natural center of balance for a humanoid fighter.

Usage:
    from normalizer import normalize_animation_frames, find_waist_anchor

    # Normalize a list of PIL Images (one per frame)
    normalized = normalize_animation_frames(
        frames=[frame1, frame2, frame3, ...],
        target_size=(96, 96),
    )

    # Or find the anchor point for a single frame
    anchor_x, anchor_y = find_waist_anchor(frame_image)
"""

from __future__ import annotations

import sys
import os
from typing import List, Tuple, Optional, Dict

import numpy as np
from PIL import Image

# Import from sibling module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyzer import create_content_mask, detect_bg_mode


# --- Waist Detection ----------------------------------------------------

def find_waist_anchor(
    frame: Image.Image,
    bg_mode: str = "auto",
    method: str = "groin",
) -> Tuple[int, int]:
    """
    Find the waist/groin anchor point of a sprite character.

    The groin is the natural pivot point for a fighting game character.
    When the groin stays at the same screen position across frames,
    the animation looks stable even when arms and legs move wildly.

    Parameters:
        frame: PIL Image (RGBA) of a single sprite frame
        bg_mode: "auto", "transparent", "green", "dark", "light"
        method: "groin" (default), "silhouette", or "ratio"

    Returns:
        (anchor_x, anchor_y) in frame-local coordinates

    Methods:
        "groin" — Fixed position at ~65% down from top, centered horizontally.
        This is where the legs meet the torso. Stays stable across ALL poses
        (idle, kick, punch, crouch, hit) because the pelvis doesn't move much.

        "silhouette" — Find the narrowest horizontal cross-section of
        the character in the torso region. More precise for idle poses
        but shifts during attacks when arms spread.

        "ratio" — Fixed 60% down from top. Simplest fallback.
    """
    arr = np.array(frame.convert("RGBA"))

    if bg_mode == "auto":
        bg_mode = detect_bg_mode(arr)

    mask = create_content_mask(arr, bg_mode=bg_mode)

    if not np.any(mask):
        # Empty frame — return center as fallback
        w, h = frame.size
        return (w // 2, h // 2)

    # Find bounding box of content
    rows_any = np.any(mask, axis=1)
    cols_any = np.any(mask, axis=0)
    rmin, rmax = np.where(rows_any)[0][[0, -1]]
    cmin, cmax = np.where(cols_any)[0][[0, -1]]

    height = rmax - rmin + 1
    width = cmax - cmin + 1
    center_x = cmin + width // 2

    if method == "groin":
        return _find_groin_anchor(mask, rmin, rmax, cmin, cmax, center_x)
    elif method == "silhouette":
        return _find_waist_silhouette(mask, rmin, rmax, cmin, cmax, center_x)
    else:
        return _find_waist_ratio(rmin, rmax, center_x)


def _find_groin_anchor(
    mask: np.ndarray,
    rmin: int, rmax: int,
    cmin: int, cmax: int,
    center_x: int,
) -> Tuple[int, int]:
    """
    Find the groin anchor — where legs meet torso.
    
    This is the MOST STABLE anchor point across all fighting game poses.
    The pelvis barely moves between idle, kick, punch, and hit animations.
    
    Method:
    1. Look at the lower 40% of the sprite (hips and legs)
    2. Find where the silhouette SPLITS from one blob into two legs
    3. That split point is the groin
    
    If we can't find a clear split, fall back to 65% down from top.
    """
    height = rmax - rmin + 1
    
    # Scan from 50% down to 80% down — this is the groin/hip region
    scan_start = rmin + int(height * 0.50)
    scan_end = rmin + int(height * 0.80)
    scan_start = max(scan_start, 0)
    scan_end = min(scan_end, mask.shape[0] - 1)
    
    # For each row, count how many "islands" of content there are
    # (1 blob = torso+legs together, 2 blobs = two separate legs)
    best_groin_y = None
    
    for r in range(scan_start, scan_end + 1):
        row = mask[r, :]
        # Find transitions from background to content
        transitions = 0
        in_content = False
        for val in row:
            if val and not in_content:
                transitions += 1
                in_content = True
            elif not val:
                in_content = False
        
        # 1 transition = one blob, 2 transitions = two legs
        # The groin is just ABOVE where it splits to 2
        if transitions >= 2:
            best_groin_y = r - 1  # One row above the split
            break
    
    if best_groin_y is None:
        # No clear leg split found — use fixed ratio
        best_groin_y = rmin + int(height * 0.65)
    
    # Find horizontal center of the torso at the groin level
    # (look at a few rows above the groin for the torso width)
    torso_rows = range(max(0, best_groin_y - 8), best_groin_y + 1)
    torso_cols = []
    for r in torso_rows:
        if r < mask.shape[0]:
            cols_in_row = np.where(mask[r, :])[0]
            if len(cols_in_row) > 0:
                torso_cols.extend(cols_in_row.tolist())
    
    if torso_cols:
        groin_x = int(np.mean(torso_cols))
    else:
        groin_x = center_x
    
    return (groin_x, best_groin_y)


def _find_waist_silhouette(
    mask: np.ndarray,
    rmin: int, rmax: int,
    cmin: int, cmax: int,
    center_x: int,
) -> Tuple[int, int]:
    """
    Find waist by scanning the silhouette for its narrowest point
    in the torso region (30%-70% of height from top).

    The waist is where the character's body cinches inward — for
    humanoid fighters this is a reliable anchor point.
    """
    height = rmax - rmin + 1

    # Define torso region: 30% to 70% from top
    # (above = head/shoulders, below = hips/legs)
    torso_start = rmin + int(height * 0.30)
    torso_end = rmin + int(height * 0.70)
    torso_start = max(torso_start, 0)
    torso_end = min(torso_end, mask.shape[0] - 1)

    # For each row in the torso, measure the width of the silhouette
    row_widths = []
    for r in range(torso_start, torso_end + 1):
        cols_in_row = np.where(mask[r, :])[0]
        if len(cols_in_row) >= 2:
            row_width = cols_in_row[-1] - cols_in_row[0] + 1
        elif len(cols_in_row) == 1:
            row_width = 1
        else:
            row_width = 0
        row_widths.append((r, row_width))

    if not row_widths:
        # Fallback to ratio method
        return _find_waist_ratio(rmin, rmax, center_x)

    # Find the narrowest row — this is the waist cinch
    # Filter out rows that are too narrow (might be a gap between arms/body)
    valid_rows = [(r, w) for r, w in row_widths if w >= 3]

    if not valid_rows:
        # Use the widest row if nothing passes the filter
        valid_rows = row_widths

    # Find narrowest point among valid rows
    waist_row = min(valid_rows, key=lambda x: x[1])[0]

    # Find the horizontal center of the silhouette at the waist row
    cols_at_waist = np.where(mask[waist_row, :])[0]
    if len(cols_at_waist) > 0:
        waist_x = int(np.mean(cols_at_waist))
    else:
        waist_x = center_x

    return (waist_x, waist_row)


def _find_waist_ratio(
    rmin: int, rmax: int,
    center_x: int,
) -> Tuple[int, int]:
    """
    Simple ratio-based waist: 60% down from top of bounding box.
    Fast and works for any humanoid shape.
    """
    height = rmax - rmin + 1
    waist_y = rmin + int(height * 0.60)
    return (center_x, waist_y)


def find_feet_anchor(
    frame: Image.Image,
    bg_mode: str = "auto",
) -> Tuple[int, int]:
    """
    Find the feet/ground contact point of a sprite.
    Used for grounding characters so they don't float.

    Returns:
        (center_x, bottom_y) of the lowest visible pixels
    """
    arr = np.array(frame.convert("RGBA"))

    if bg_mode == "auto":
        bg_mode = detect_bg_mode(arr)

    mask = create_content_mask(arr, bg_mode=bg_mode)

    if not np.any(mask):
        w, h = frame.size
        return (w // 2, h)

    rows_any = np.any(mask, axis=1)
    cols_any = np.any(mask, axis=0)

    rmin, rmax = np.where(rows_any)[0][[0, -1]]
    cmin, cmax = np.where(cols_any)[0][[0, -1]]

    # Find the lowest row with content in the center 50% of the sprite
    # (ignores weapons/effects that extend below feet)
    center_start = cmin + (cmax - cmin) * 25 // 100
    center_end = cmin + (cmax - cmin) * 75 // 100
    center_cols = mask[:, int(center_start):int(center_end) + 1]

    if np.any(center_cols):
        bottom_rows = np.where(np.any(center_cols, axis=1))[0]
        feet_y = int(bottom_rows[-1])
    else:
        feet_y = rmax

    center_x = cmin + (cmax - cmin) // 2
    return (center_x, feet_y)


# --- Frame Extraction ---------------------------------------------------

def extract_sprite(
    frame: Image.Image,
    bg_mode: str = "auto",
    padding: int = 4,
) -> Tuple[Optional[Image.Image], Tuple[int, int]]:
    """
    Extract the sprite from a frame, removing background.

    Returns:
        (sprite_image, (origin_x, origin_y)) or (None, (0,0)) if empty
    """
    arr = np.array(frame.convert("RGBA"))

    if bg_mode == "auto":
        bg_mode = detect_bg_mode(arr)

    mask = create_content_mask(arr, bg_mode=bg_mode)

    if not np.any(mask):
        return None, (0, 0)

    rows_any = np.any(mask, axis=1)
    cols_any = np.any(mask, axis=0)
    rmin, rmax = np.where(rows_any)[0][[0, -1]]
    cmin, cmax = np.where(cols_any)[0][[0, -1]]

    # Crop with padding
    rmin = max(0, rmin - padding)
    cmin = max(0, cmin - padding)
    rmax = min(arr.shape[0] - 1, rmax + padding)
    cmax = min(arr.shape[1] - 1, cmax + padding)

    sprite = frame.crop((cmin, rmin, cmax + 1, rmax + 1))
    return sprite, (cmin, rmin)


# --- Normalization ------------------------------------------------------

def normalize_animation_frames(
    frames: List[Image.Image],
    target_size: Tuple[int, int] = (96, 96),
    anchor_method: str = "silhouette",
    bg_mode: str = "auto",
    anchor_target: Optional[Tuple[float, float]] = None,
    ground_feet: bool = True,
) -> List[Image.Image]:
    """
    Normalize a set of animation frames to have consistent anchoring.

    This is the CORE function that fixes the "jumping" problem.
    For each frame:
      1. Find the waist anchor point
      2. Extract the sprite content
      3. Scale to fit target_size
      4. Place sprite so waist anchor is at the same position in every frame

    Parameters:
        frames: List of PIL Images (one per frame, any size)
        target_size: (width, height) of output frames
        anchor_method: "silhouette" or "ratio"
        bg_mode: background detection mode
        anchor_target: (x_ratio, y_ratio) where anchor should land
                       Default: (0.5, 0.55) = center horizontally, 55% down
        ground_feet: If True, also ensure feet are near the bottom

    Returns:
        List of normalized PIL Images (RGBA, target_size)
    """
    if not frames:
        return []

    if anchor_target is None:
        anchor_target = (0.5, 0.55)  # Center X, 55% down Y

    target_w, target_h = target_size
    target_anchor_x = int(target_w * anchor_target[0])
    target_anchor_y = int(target_h * anchor_target[1])

    normalized = []

    for frame in frames:
        # Step 1: Find anchor in original frame
        anchor_x, anchor_y = find_waist_anchor(
            frame, bg_mode=bg_mode, method=anchor_method
        )

        # Step 2: Extract sprite
        sprite, (orig_x, orig_y) = extract_sprite(frame, bg_mode=bg_mode)

        if sprite is None:
            normalized.append(Image.new("RGBA", target_size, (0, 0, 0, 0)))
            continue

        sprite_w, sprite_h = sprite.size

        if sprite_w == 0 or sprite_h == 0:
            normalized.append(Image.new("RGBA", target_size, (0, 0, 0, 0)))
            continue

        # Step 3: Scale sprite to fit within target (with margin)
        margin = 4
        max_w = target_w - margin * 2
        max_h = target_h - margin * 2
        scale = min(max_w / sprite_w, max_h / sprite_h, 1.0)

        new_w = max(1, int(sprite_w * scale))
        new_h = max(1, int(sprite_h * scale))
        sprite_scaled = sprite.resize((new_w, new_h), Image.NEAREST)

        # Step 4: Calculate where the anchor lands in the scaled sprite
        # Anchor position relative to sprite origin
        anchor_rel_x = anchor_x - orig_x
        anchor_rel_y = anchor_y - orig_y

        # Scale the relative anchor position
        anchor_scaled_x = anchor_rel_x * scale
        anchor_scaled_y = anchor_rel_y * scale

        # Step 5: Calculate paste position to align anchor with target
        paste_x = int(target_anchor_x - anchor_scaled_x)
        paste_y = int(target_anchor_y - anchor_scaled_y)

        # Step 6: Optional feet grounding
        # If ground_feet is True, adjust vertical position so feet
        # are near the bottom of the frame (prevent floating)
        if ground_feet:
            feet_anchor = find_feet_anchor(frame, bg_mode=bg_mode)
            feet_rel_y = feet_anchor[1] - orig_y
            feet_scaled_y = feet_rel_y * scale
            feet_absolute_y = paste_y + feet_scaled_y

            # Target: feet should be at target_h - 8 (8px from bottom)
            target_feet_y = target_h - 8
            feet_correction = target_feet_y - feet_absolute_y

            # Only correct downward (don't push character up past waist anchor)
            # Use a blend: 60% waist anchor, 40% feet grounding
            if feet_correction > 0:
                paste_y += int(feet_correction * 0.4)

        # Step 7: Create normalized frame and paste
        result = Image.new("RGBA", target_size, (0, 0, 0, 0))
        result.paste(sprite_scaled, (paste_x, paste_y), sprite_scaled)
        normalized.append(result)

    return normalized


def normalize_from_bounds(
    source_sheet: Image.Image,
    frame_bounds: List[Tuple[int, int, int, int]],
    target_size: Tuple[int, int] = (96, 96),
    anchor_method: str = "silhouette",
    bg_mode: str = "auto",
) -> Tuple[List[Image.Image], List[Tuple[int, int]]]:
    """
    Normalize frames from a sprite sheet using detected bounds.

    Parameters:
        source_sheet: The full sprite sheet image
        frame_bounds: List of (x, y, w, h) tuples from analyzer
        target_size: Output frame size
        anchor_method: "silhouette" or "ratio"
        bg_mode: Background detection mode

    Returns:
        (normalized_frames, anchor_points) — the frames and the anchor
        points that were used (for debugging/visualization)
    """
    frames = []
    for x, y, w, h in frame_bounds:
        crop = source_sheet.crop((x, y, x + w, y + h))
        frames.append(crop)

    anchors = []
    for frame in frames:
        anchor = find_waist_anchor(frame, bg_mode=bg_mode, method=anchor_method)
        anchors.append(anchor)

    normalized = normalize_animation_frames(
        frames,
        target_size=target_size,
        anchor_method=anchor_method,
        bg_mode=bg_mode,
    )

    return normalized, anchors


# --- Anchor Visualization (for debugging) -------------------------------

def visualize_anchors(
    frame: Image.Image,
    bg_mode: str = "auto",
    anchor_method: str = "silhouette",
) -> Image.Image:
    """
    Draw anchor points on a frame for visual debugging.
    Returns a new image with markers showing detected anchors.
    """
    vis = frame.copy()
    arr = np.array(vis.convert("RGBA"))

    if bg_mode == "auto":
        bg_mode = detect_bg_mode(arr)

    # Get anchors
    waist = find_waist_anchor(frame, bg_mode=bg_mode, method=anchor_method)
    feet = find_feet_anchor(frame, bg_mode=bg_mode)

    from PIL import ImageDraw
    draw = ImageDraw.Draw(vis)

    # Draw waist anchor: red crosshair
    wx, wy = waist
    r = 6
    draw.line((wx - r, wy, wx + r, wy), fill=(255, 0, 0, 255), width=2)
    draw.line((wx, wy - r, wx, wy + r), fill=(255, 0, 0, 255), width=2)
    draw.ellipse((wx - 3, wy - 3, wx + 3, wy + 3), outline=(255, 0, 0, 255))

    # Draw feet anchor: blue line
    fx, fy = feet
    draw.line((fx - 8, fy, fx + 8, fy), fill=(0, 100, 255, 255), width=2)

    # Label
    draw.text((2, 2), f"W:{wx},{wy}", fill=(255, 0, 0, 255))
    draw.text((2, 14), f"F:{fx},{fy}", fill=(0, 100, 255, 255))

    return vis


def create_anchor_debug_sheet(
    frames: List[Image.Image],
    bg_mode: str = "auto",
    anchor_method: str = "silhouette",
) -> Image.Image:
    """
    Create a debug sheet showing all frames with their anchor points.
    Useful for verifying that anchors are detected consistently.
    """
    vis_frames = [visualize_anchors(f, bg_mode, anchor_method) for f in frames]

    if not vis_frames:
        return Image.new("RGBA", (100, 100), (0, 0, 0, 0))

    frame_w = max(f.size[0] for f in vis_frames)
    frame_h = max(f.size[1] for f in vis_frames)

    cols = min(len(vis_frames), 8)
    rows = (len(vis_frames) + cols - 1) // cols

    sheet_w = cols * (frame_w + 4) + 4
    sheet_h = rows * (frame_h + 20) + 4  # Extra height for labels

    sheet = Image.new("RGBA", (sheet_w, sheet_h), (20, 20, 30, 255))
    from PIL import ImageDraw
    draw = ImageDraw.Draw(sheet)

    for i, vis in enumerate(vis_frames):
        col = i % cols
        row = i // cols
        x = col * (frame_w + 4) + 4
        y = row * (frame_h + 20) + 4

        # Center the frame in its cell
        fw, fh = vis.size
        x_offset = (frame_w - fw) // 2

        sheet.paste(vis, (x + x_offset, y))
        draw.text((x + 2, y + frame_h + 2), f"F{i:02d}", fill=(180, 180, 180, 255))
        draw.rectangle(
            (x - 1, y - 1, x + frame_w, y + frame_h),
            outline=(60, 60, 60, 255),
        )

    return sheet


# --- CLI ---------------------------------------------------------------

def _cli():
    import argparse

    parser = argparse.ArgumentParser(
        description="Sprite Forge Normalizer — align sprite frames"
    )
    parser.add_argument("input", help="Input sprite sheet PNG")
    parser.add_argument("-o", "--output", default="normalized.png",
                        help="Output sheet PNG (default: normalized.png)")
    parser.add_argument("--size", type=int, default=96,
                        help="Target frame size (default: 96)")
    parser.add_argument("--anchor", choices=["silhouette", "ratio"],
                        default="silhouette",
                        help="Anchor detection method (default: silhouette)")
    parser.add_argument("--bg", choices=["auto", "transparent", "green", "dark", "light"],
                        default="auto",
                        help="Background mode (default: auto)")
    parser.add_argument("--debug", action="store_true",
                        help="Output debug sheet with anchor points")
    parser.add_argument("--anchor-json", default=None,
                        help="Write anchor points to JSON file")

    args = parser.parse_args()

    img = Image.open(args.input).convert("RGBA")
    print(f"Loaded: {args.input} ({img.size[0]}x{img.size[1]})")

    # Detect frames using analyzer
    from analyzer import create_content_mask, find_frame_bounds
    arr = np.array(img)
    bg_mode = args.bg
    if bg_mode == "auto":
        bg_mode = detect_bg_mode(arr)

    mask = create_content_mask(arr, bg_mode=bg_mode)
    bounds = find_frame_bounds(mask)
    print(f"Detected {len(bounds)} frames")

    # Normalize
    target_size = (args.size, args.size)
    normalized, anchors = normalize_from_bounds(
        img, bounds,
        target_size=target_size,
        anchor_method=args.anchor,
        bg_mode=bg_mode,
    )

    # Build output sheet
    cols = min(len(normalized), 10)
    rows = (len(normalized) + cols - 1) // cols
    sheet_w = cols * (args.size + 4) + 4
    sheet_h = rows * (args.size + 4) + 4

    sheet = Image.new("RGBA", (sheet_w, sheet_h), (0, 0, 0, 0))
    for i, frame in enumerate(normalized):
        col = i % cols
        row = i // cols
        x = col * (args.size + 4) + 4
        y = row * (args.size + 4) + 4
        sheet.paste(frame, (x, y))

    sheet.save(args.output)
    print(f"Wrote: {args.output} ({sheet_w}x{sheet_h})")

    # Anchor stats
    print(f"\nAnchor points ({args.anchor} method):")
    for i, (ax, ay) in enumerate(anchors):
        print(f"  Frame {i:2d}: ({ax:4d}, {ay:4d})")

    xs = [a[0] for a in anchors]
    ys = [a[1] for a in anchors]
    print(f"\n  X range: {min(xs)}-{max(xs)} (spread: {max(xs)-min(xs)}px)")
    print(f"  Y range: {min(ys)}-{max(ys)} (spread: {max(ys)-min(ys)}px)")

    # Debug sheet
    if args.debug:
        debug_path = args.output.replace(".png", "_debug.png")
        debug = create_anchor_debug_sheet(
            [img.crop((x, y, x+w, y+h)) for x, y, w, h in bounds],
            bg_mode=bg_mode,
            anchor_method=args.anchor,
        )
        debug.save(debug_path)
        print(f"Debug sheet: {debug_path}")

    # JSON export
    if args.anchor_json:
        import json
        data = {
            "method": args.anchor,
            "bg_mode": bg_mode,
            "target_size": list(target_size),
            "anchors": [
                {"frame": i, "x": int(a[0]), "y": int(a[1])}
                for i, a in enumerate(anchors)
            ],
            "stats": {
                "x_min": int(min(xs)), "x_max": int(max(xs)),
                "y_min": int(min(ys)), "y_max": int(max(ys)),
                "x_spread": int(max(xs) - min(xs)),
                "y_spread": int(max(ys) - min(ys)),
            },
        }
        with open(args.anchor_json, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Anchor data: {args.anchor_json}")


if __name__ == "__main__":
    _cli()
