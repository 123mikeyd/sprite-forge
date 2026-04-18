#!/usr/bin/env python3
"""
Sprite Forge Analyzer
Detects frames in sprite sheets, analyzes quality, compresses, exports JSON.

Usage:
    python analyzer.py <image_path> [--bg-mode auto|green|dark|light] [--compress 0.1-1.0] [--output frames.json]

Can also be imported:
    from analyzer import detect_frames, analyze_quality, compress_sheet
"""

import json
import sys
import os
import argparse
from pathlib import Path
from PIL import Image
import numpy as np
from collections import Counter


# ─── Background Detection ───────────────────────────────────────────────

def detect_bg_color(img_arr, sample_border=10):
    """Detect the most common background color by sampling the image border."""
    h, w = img_arr.shape[:2]
    border_pixels = []

    # Sample top/bottom rows
    for y in range(min(sample_border, h)):
        border_pixels.extend(img_arr[y, :].tolist())
    for y in range(max(0, h - sample_border), h):
        border_pixels.extend(img_arr[y, :].tolist())

    # Sample left/right columns
    for x in range(min(sample_border, w)):
        border_pixels.extend(img_arr[:, x].tolist())
    for x in range(max(0, w - sample_border), w):
        border_pixels.extend(img_arr[:, x].tolist())

    # Most common color
    if img_arr.shape[2] == 4:
        # For RGBA, ignore alpha channel in counting
        tuples = [(p[0], p[1], p[2]) for p in border_pixels]
    else:
        tuples = [tuple(p) for p in border_pixels]

    most_common = Counter(tuples).most_common(1)[0][0]
    return most_common


def is_background(r, g, b, bg_color, tolerance=30):
    """Check if a pixel matches the background color within tolerance."""
    return (abs(int(r) - bg_color[0]) <= tolerance and
            abs(int(g) - bg_color[1]) <= tolerance and
            abs(int(b) - bg_color[2]) <= tolerance)


def is_transparent(r, g, b, a=None):
    """Detect fully- or mostly-transparent pixels (PNG alpha channel).

    This is the MOST RELIABLE signal when a sprite sheet has real
    transparency — the RGB channels of transparent pixels are often
    (0,0,0) or noise, so RGB-only checks misclassify sprites that
    happen to contain dark pixels as background.
    """
    if a is None:
        return False
    return a < 32


def is_green_screen(r, g, b):
    """Detect green screen background (bright green #00FF00)."""
    return r < 80 and g > 160 and b < 80


def is_dark_bg(r, g, b):
    """Detect dark/gray background (like TekxLobster style)."""
    return r < 90 and g < 90 and b < 90 and max(r, g, b) - min(r, g, b) < 20


def is_light_bg(r, g, b):
    """Detect white/light background."""
    return r > 230 and g > 230 and b > 230


def detect_bg_mode(img_arr):
    """Auto-detect the background type from the image.

    Priority:
      1. If image has alpha and >50% of border pixels are transparent → "transparent"
      2. Otherwise, sample and pick most common of green/dark/light/other
    """
    h, w = img_arr.shape[:2]

    # Alpha-first check — this is the #1 failure mode in public-domain
    # sprite sheets (they're almost always PNG with real transparency).
    if img_arr.shape[2] == 4:
        # Sample border for alpha density
        border_alphas = []
        border_alphas.extend(img_arr[0, :, 3].tolist())
        border_alphas.extend(img_arr[-1, :, 3].tolist())
        border_alphas.extend(img_arr[:, 0, 3].tolist())
        border_alphas.extend(img_arr[:, -1, 3].tolist())
        transparent_pct = sum(1 for a in border_alphas if a < 32) / len(border_alphas)
        if transparent_pct > 0.5:
            print(f"  BG detection: transparent ({transparent_pct*100:.0f}% of border is alpha<32)")
            return "transparent"

    sample_size = min(2000, h * w // 10)
    indices = np.random.choice(h * w, sample_size, replace=False)

    counts = {"green": 0, "dark": 0, "light": 0, "other": 0}

    for idx in indices:
        y, x = divmod(idx, w)
        r, g, b = int(img_arr[y, x, 0]), int(img_arr[y, x, 1]), int(img_arr[y, x, 2])

        if is_green_screen(r, g, b):
            counts["green"] += 1
        elif is_dark_bg(r, g, b):
            counts["dark"] += 1
        elif is_light_bg(r, g, b):
            counts["light"] += 1
        else:
            counts["other"] += 1

    winner = max(counts, key=counts.get)
    pct = counts[winner] / sample_size * 100
    print(f"  BG detection: {winner} ({pct:.0f}% of sampled pixels)")
    return winner


def create_content_mask(img_arr, bg_mode="auto", tolerance=30):
    """Create a boolean mask where True = content pixel, False = background."""
    h, w = img_arr.shape[:2]
    mask = np.zeros((h, w), dtype=bool)

    if bg_mode == "auto":
        bg_mode = detect_bg_mode(img_arr)

    bg_color = detect_bg_color(img_arr) if bg_mode == "custom" else None
    has_alpha = img_arr.shape[2] == 4

    # Fast vectorized path for "transparent" mode (the common case for
    # public-domain sprite sheets). Much faster than the Python loop.
    if bg_mode == "transparent":
        if has_alpha:
            mask = img_arr[:, :, 3] >= 32
            return mask
        # No alpha channel but caller asked for transparent — fall back to dark
        bg_mode = "dark"

    for y in range(h):
        for x in range(w):
            r, g, b = int(img_arr[y, x, 0]), int(img_arr[y, x, 1]), int(img_arr[y, x, 2])
            a = int(img_arr[y, x, 3]) if has_alpha else None

            if bg_mode == "green":
                if not is_green_screen(r, g, b):
                    mask[y, x] = True
            elif bg_mode == "dark":
                if not is_dark_bg(r, g, b):
                    mask[y, x] = True
            elif bg_mode == "light":
                if not is_light_bg(r, g, b):
                    mask[y, x] = True
            elif bg_color:
                if not is_background(r, g, b, bg_color, tolerance):
                    mask[y, x] = True

    return mask


# ─── Frame Detection ─────────────────────────────────────────────────────

def find_frame_bounds(mask, min_width=8, min_height=8, padding=5):
    """
    Detect individual sprite frames from a content mask.
    Returns list of (x, y, w, h) bounding boxes.

    min_width/min_height default to 8 — deliberately low so small pixel-art
    sprites (16x16 tiles, narrow idle poses) aren't filtered out. Set higher
    only if the sheet has isolated-pixel noise that's being picked up as
    tiny frames.
    """
    h, w = mask.shape

    # Find horizontal gaps (row groups)
    row_has_content = np.any(mask, axis=1)
    row_groups = []
    in_group = False
    start = 0

    for i in range(h):
        if row_has_content[i] and not in_group:
            start = i
            in_group = True
        elif not row_has_content[i] and in_group:
            if i - start >= min_height:
                row_groups.append((start, i - 1))
            in_group = False
    if in_group and h - start >= min_height:
        row_groups.append((start, h - 1))

    frames = []

    for y1, y2 in row_groups:
        height = y2 - y1 + 1
        row_mask = mask[y1:y2 + 1, :]
        col_in_row = np.any(row_mask, axis=0)

        # Find column groups within this row
        col_groups = []
        in_col = False
        col_start = 0

        for j in range(w):
            if col_in_row[j] and not in_col:
                col_start = j
                in_col = True
            elif not col_in_row[j] and in_col:
                if j - col_start >= min_width:
                    col_groups.append((col_start, j - 1))
                in_col = False
        if in_col and w - col_start >= min_width:
            col_groups.append((col_start, w - 1))

        # Check for merged sprites (two sprites in one bounding box)
        for x1, x2 in col_groups:
            sprite_width = x2 - x1 + 1

            # Column density analysis to find internal splits
            col_density = np.zeros(sprite_width)
            for dx in range(sprite_width):
                col_density[dx] = np.sum(row_mask[:, x1 + dx])

            # Find significant gaps within the sprite
            threshold = max(2, np.max(col_density) * 0.05)
            gap_mask = col_density < threshold
            gaps = []
            in_gap = False
            gap_start = 0

            for gi in range(sprite_width):
                if gap_mask[gi] and not in_gap:
                    gap_start = gi
                    in_gap = True
                elif not gap_mask[gi] and in_gap:
                    if gi - gap_start >= 15:  # minimum gap width for a split
                        gaps.append((gap_start, gi - 1))
                    in_gap = False
            if in_gap and sprite_width - gap_start >= 15:
                gaps.append((gap_start, sprite_width - 1))

            if gaps:
                # Split at the widest gap
                widest = max(gaps, key=lambda g: g[1] - g[0])
                split_x = x1 + (widest[0] + widest[1]) // 2

                # Validate both halves are wide enough
                left_w = split_x - x1
                right_w = x2 - split_x
                if left_w >= min_width and right_w >= min_width:
                    # Apply padding
                    fx1 = max(0, x1 - padding)
                    fy1 = max(0, y1 - padding)
                    frames.append((fx1, fy1, split_x - fx1 + padding, height + padding * 2))

                    fx2 = max(0, split_x - padding)
                    frames.append((fx2, fy1, x2 - fx2 + padding, height + padding * 2))
                    continue

            # No split needed
            fx = max(0, x1 - padding)
            fy = max(0, y1 - padding)
            fw = min(w - fx, sprite_width + padding * 2)
            fh = min(h - fy, height + padding * 2)
            frames.append((fx, fy, fw, fh))

    # Sort by row then column
    frames.sort(key=lambda f: (f[1], f[0]))
    return frames


def merge_similar_rows(frames, row_tolerance=20):
    """Group frames that are on the same row (same y-position)."""
    if not frames:
        return frames

    frames_sorted = sorted(frames, key=lambda f: f[1])
    rows = []
    current_row = [frames_sorted[0]]
    row_y = frames_sorted[0][1]

    for f in frames_sorted[1:]:
        if abs(f[1] - row_y) <= row_tolerance:
            current_row.append(f)
        else:
            rows.append(sorted(current_row, key=lambda f: f[0]))
            current_row = [f]
            row_y = f[1]
    rows.append(sorted(current_row, key=lambda f: f[0]))

    return rows


# ─── Quality Analysis ────────────────────────────────────────────────────

def analyze_frame_quality(img, frame_bounds, bg_mode="auto"):
    """Analyze quality metrics for a single frame."""
    x, y, w, h = frame_bounds
    crop = img.crop((x, y, x + w, y + h))
    arr = np.array(crop)

    metrics = {
        "bounds": [int(x), int(y), int(w), int(h)],
        "dimensions": {"width": int(w), "height": int(h)},
        "aspect_ratio": round(w / h, 2) if h > 0 else 0,
    }

    # Unique colors
    if arr.shape[2] == 4:
        pixels = arr[arr[:, :, 3] > 0]  # non-transparent only
    else:
        # Non-background pixels
        mask = create_content_mask(arr if arr.shape[2] == 3 else arr[:, :, :3],
                                   bg_mode=bg_mode)
        pixels = arr[mask]

    if len(pixels) == 0:
        metrics["quality"] = "empty"
        metrics["unique_colors"] = 0
        metrics["pixel_density"] = 0.0
        return metrics

    unique_colors = len(np.unique(pixels[:, :3].reshape(-1, 3), axis=0))
    total_pixels = w * h
    content_pixels = len(pixels)
    pixel_density = content_pixels / total_pixels

    # Edge sharpness (variance of Laplacian proxy — difference of neighboring pixels)
    if arr.shape[0] > 2 and arr.shape[1] > 2:
        gray = np.mean(arr[:, :, :3], axis=2)
        laplacian = (np.abs(np.diff(gray, axis=0)).mean() +
                     np.abs(np.diff(gray, axis=1)).mean()) / 2
        edge_sharpness = min(1.0, laplacian / 30.0)
    else:
        edge_sharpness = 0.5

    # Color variance
    color_var = float(np.std(pixels[:, :3]))

    metrics["unique_colors"] = int(unique_colors)
    metrics["pixel_density"] = round(pixel_density, 3)
    metrics["edge_sharpness"] = round(edge_sharpness, 3)
    metrics["color_variance"] = round(color_var, 1)

    # Quality label
    if pixel_density < 0.05:
        metrics["quality"] = "empty"
    elif pixel_density < 0.15:
        metrics["quality"] = "sparse"
    elif edge_sharpness < 0.1:
        metrics["quality"] = "blurry"
    elif unique_colors > 200:
        metrics["quality"] = "noisy"
    else:
        metrics["quality"] = "good"

    return metrics


def detect_duplicates(frames_quality, threshold=0.92):
    """Detect likely duplicate frames based on quality metrics similarity."""
    duplicates = []

    for i in range(len(frames_quality)):
        for j in range(i + 1, len(frames_quality)):
            a = frames_quality[i]
            b = frames_quality[j]

            # Skip empty frames
            if a.get("quality") == "empty" or b.get("quality") == "empty":
                continue

            # Compare dimensions
            if a["dimensions"] != b["dimensions"]:
                continue

            # Simple heuristic: same dimensions + similar pixel density + similar colors
            density_sim = 1 - abs(a["pixel_density"] - b["pixel_density"])
            color_sim = 1 - min(1, abs(a["unique_colors"] - b["unique_colors"]) /
                                max(a["unique_colors"], b["unique_colors"], 1))

            similarity = (density_sim + color_sim) / 2

            if similarity >= threshold:
                duplicates.append({
                    "frame_a": i,
                    "frame_b": j,
                    "similarity": round(similarity, 3)
                })

    return duplicates


# ─── Compression ──────────────────────────────────────────────────────────

def compress_sheet(img, quality=0.5, method="resize"):
    """
    Compress a sprite sheet to reduce complexity.
    quality: 0.1 (very compressed) to 1.0 (original)
    method: "resize" (scale down) or "palette" (reduce colors)
    """
    if quality >= 1.0:
        return img

    w, h = img.size

    if method == "resize":
        scale = quality
        new_w = max(32, int(w * scale))
        new_h = max(32, int(h * scale))
        return img.resize((new_w, new_h), Image.NEAREST)

    elif method == "palette":
        # Reduce to N colors
        num_colors = max(2, int(16 * quality + 2))
        img_rgb = img.convert("RGB")
        quantized = img_rgb.quantize(colors=num_colors, method=Image.MEDIANCUT)
        return quantized.convert("RGBA")

    return img


# ─── Density Barcode ─────────────────────────────────────────────────────

def density_barcode(img_arr, y1, y2, x1, x2, bg_mode="auto"):
    """Generate a density barcode for visual debugging of split points."""
    row_slice = img_arr[y1:y2 + 1, x1:x2 + 1]

    if bg_mode == "auto":
        bg_mode = detect_bg_mode(row_slice)

    barcode = ""
    for dx in range(x2 - x1 + 1):
        col = row_slice[:, dx]
        d = 0
        for px in col:
            r, g, b = int(px[0]), int(px[1]), int(px[2])
            if bg_mode == "green" and not is_green_screen(r, g, b):
                d += 1
            elif bg_mode == "dark" and not is_dark_bg(r, g, b):
                d += 1
            elif bg_mode == "light" and not is_light_bg(r, g, b):
                d += 1
            else:
                d += 1

        if d == 0:
            barcode += "."
        elif d < 5:
            barcode += ","
        elif d < 20:
            barcode += ":"
        elif d < 50:
            barcode += "o"
        else:
            barcode += "#"

    return barcode


# ─── Full Pipeline ────────────────────────────────────────────────────────

def analyze_sheet(image_path, bg_mode="auto", compress=1.0, padding=5,
                  min_width=8, min_height=8):
    """
    Full analysis pipeline: load → compress → detect → analyze → return results.
    Returns dict with all analysis data.
    """
    img = Image.open(image_path).convert("RGBA")
    original_size = img.size

    # Compression pass
    if compress < 1.0:
        img = compress_sheet(img, quality=compress, method="resize")
        print(f"  Compressed: {original_size} -> {img.size}")

    img_arr = np.array(img)
    h, w = img_arr.shape[:2]

    # Detect background
    if bg_mode == "auto":
        bg_mode = detect_bg_mode(img_arr)

    # Create content mask
    print("  Creating content mask...")
    mask = create_content_mask(img_arr, bg_mode=bg_mode)

    # Find frames
    print("  Detecting frames...")
    frames = find_frame_bounds(mask, min_width=min_width, min_height=min_height,
                               padding=padding)
    print(f"  Found {len(frames)} frames")

    # Group into rows
    rows = merge_similar_rows(frames)

    # Analyze each frame
    print("  Analyzing frame quality...")
    frame_data = []
    for i, bounds in enumerate(frames):
        metrics = analyze_frame_quality(img, bounds, bg_mode=bg_mode)
        metrics["index"] = i
        frame_data.append(metrics)

    # Detect duplicates
    print("  Checking for duplicates...")
    duplicates = detect_duplicates(frame_data)

    # Background info
    bg_color = detect_bg_color(img_arr)

    result = {
        "image_path": str(image_path),
        "original_size": list(original_size),
        "current_size": [w, h],
        "bg_mode": bg_mode,
        "bg_color": list(bg_color),
        "compression": compress,
        "total_frames": len(frames),
        "rows": len(rows),
        "frames": frame_data,
        "duplicates": duplicates,
        "row_groups": [
            [{"index": frames.index(f), "bounds": list(f)} for f in row]
            for row in rows
        ],
        "summary": {
            "good": sum(1 for f in frame_data if f.get("quality") == "good"),
            "empty": sum(1 for f in frame_data if f.get("quality") == "empty"),
            "sparse": sum(1 for f in frame_data if f.get("quality") == "sparse"),
            "blurry": sum(1 for f in frame_data if f.get("quality") == "blurry"),
            "noisy": sum(1 for f in frame_data if f.get("quality") == "noisy"),
        }
    }

    return result


def export_keyed_sheet(image_path, bg_mode="auto", compress=1.0, output_path=None):
    """
    Export the sprite sheet with background removed (transparent).
    """
    img = Image.open(image_path).convert("RGBA")
    if compress < 1.0:
        img = compress_sheet(img, quality=compress, method="resize")

    arr = np.array(img)
    h, w = arr.shape[:2]

    if bg_mode == "auto":
        bg_mode = detect_bg_mode(arr)

    bg_color = detect_bg_color(arr)

    for y in range(h):
        for x in range(w):
            r, g, b = int(arr[y, x, 0]), int(arr[y, x, 1]), int(arr[y, x, 2])
            is_bg = False

            if bg_mode == "green" and is_green_screen(r, g, b):
                is_bg = True
            elif bg_mode == "dark" and is_dark_bg(r, g, b):
                is_bg = True
            elif bg_mode == "light" and is_light_bg(r, g, b):
                is_bg = True
            elif bg_mode == "transparent":
                # Already has alpha; pass through unchanged
                is_bg = False

            if is_bg:
                arr[y, x, 3] = 0

    result = Image.fromarray(arr)

    if output_path:
        result.save(output_path)
        print(f"  Saved keyed sheet: {output_path}")

    return result


# ─── CLI ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Sprite Forge Analyzer")
    parser.add_argument("image", help="Path to sprite sheet image")
    parser.add_argument("--bg-mode", choices=["auto", "green", "dark", "light", "transparent"],
                        default="auto", help="Background detection mode")
    parser.add_argument("--compress", type=float, default=1.0,
                        help="Compression factor 0.1-1.0 (1.0 = original)")
    parser.add_argument("--padding", type=int, default=5,
                        help="Padding around detected frames (pixels)")
    parser.add_argument("--min-width", type=int, default=8,
                        help="Minimum frame width to detect (default 8)")
    parser.add_argument("--min-height", type=int, default=8,
                        help="Minimum frame height to detect (default 8)")
    parser.add_argument("--output", "-o", help="Output JSON path (default: <image>_frames.json)")
    parser.add_argument("--keyed", help="Export background-removed sheet to this path")
    parser.add_argument("--quiet", "-q", action="store_true", help="Less output")

    args = parser.parse_args()

    if not Path(args.image).exists():
        print(f"Error: {args.image} not found")
        sys.exit(1)

    if not args.quiet:
        print(f"Analyzing: {args.image}")
        print(f"  BG mode: {args.bg_mode}")
        print(f"  Compression: {args.compress}")

    result = analyze_sheet(
        args.image,
        bg_mode=args.bg_mode,
        compress=args.compress,
        padding=args.padding,
        min_width=args.min_width,
        min_height=args.min_height
    )

    # Output
    output_path = args.output or str(Path(args.image).stem + "_frames.json")
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    if not args.quiet:
        print(f"\n  Results: {output_path}")
        print(f"  Frames found: {result['total_frames']}")
        print(f"  Rows: {result['rows']}")
        print(f"  Quality: {result['summary']}")
        if result['duplicates']:
            print(f"  Potential duplicates: {len(result['duplicates'])}")

    # Export keyed sheet if requested
    if args.keyed:
        export_keyed_sheet(args.image, bg_mode=args.bg_mode,
                           compress=args.compress, output_path=args.keyed)

    return result


if __name__ == "__main__":
    main()
