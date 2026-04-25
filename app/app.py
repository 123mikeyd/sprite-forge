#!/usr/bin/env python3
"""
Sprite Forge — Self-contained sprite sheet generator for 2D fighters.

Run:  python3 app.py
Open: http://localhost:5000

One Flask server. One browser tab. Complete workflow:
  Welcome → Character Prompt → Reference Image → Approve/Reject
  → Idle + Walk → Review → Punch + Kick → Review
  → Jump + Special → Review → Final Sheet + Download
"""

import os
import json
import base64
import hashlib
import tempfile
from datetime import datetime
from pathlib import Path

import requests
import numpy as np
from PIL import Image
from flask import Flask, request, jsonify, send_file, render_template_string

# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════

FAL_KEY = os.environ.get("FAL_KEY", "")
FAL_MODEL = "fal-ai/flux/dev"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

# ═══════════════════════════════════════════════════════════════════════
# PROMPT TEMPLATES
# ═══════════════════════════════════════════════════════════════════════

PROMPTS = {
    "reference": (
        "Side-view pixel art character sprite for a 2D fighting game, facing RIGHT. "
        "{character}. Standing in neutral fighting stance, weight balanced, "
        "hands up in guard position, knees slightly bent. "
        "Character viewed from the SIDE like Street Fighter. "
        "Bright MAGENTA #FF00FF solid background. NOT green, NOT blue — pure magenta. "
        "Centered in frame, fully visible head to feet, no cropping at edges. "
        "Clean pixel art style, saturated colors, clear silhouette."
    ),

    "idle_walk": (
        "Side-view pixel art sprite sheet for 2D fighting game, character faces RIGHT. "
        "{character}. "
        "2x2 grid with CLEAR BLACK BORDERS between 4 cells, each cell same size. "
        "Cell 1 (top-left): Idle stance frame 1, neutral guard, weight balanced. "
        "Cell 2 (top-right): Walk frame 1, RIGHT foot stepping forward, left foot behind, "
        "arms swinging opposite to legs. "
        "Cell 3 (bottom-left): Walk frame 2, MIDSTRIDE, both feet crossing near center, "
        "body at lowest point of stride. "
        "Cell 4 (bottom-right): Walk frame 3, LEFT foot stepping forward past right, "
        "opposite of cell 2. "
        "All poses SIDE-VIEW like Street Fighter. "
        "Bright MAGENTA #FF00FF background in each cell. NOT green, NOT blue — pure magenta. "
        "Character centered and fully visible in each cell."
    ),

    "punch_kick": (
        "Side-view pixel art sprite sheet for 2D fighting game, character faces RIGHT. "
        "{character}. "
        "2x2 grid with CLEAR BLACK BORDERS between 4 cells, each cell same size. "
        "Cell 1 (top-left): Punch WIND-UP, pulling right fist back near shoulder, "
        "torso twisting to load power. "
        "Cell 2 (top-right): Punch FULL EXTENSION, right fist thrust forward at full reach, "
        "torso rotated, weight on front foot. "
        "Cell 3 (bottom-left): Kick CHAMBER, right knee raised high, "
        "leaning back slightly, arms out for balance. "
        "Cell 4 (bottom-right): Kick FULL EXTENSION, right leg straight out, "
        "foot at maximum reach, body leaning back. "
        "All poses SIDE-VIEW like Street Fighter. "
        "Bright MAGENTA #FF00FF background in each cell. NOT green, NOT blue — pure magenta. "
        "Character centered and fully visible in each cell."
    ),

    "jump_special": (
        "Side-view pixel art sprite sheet for 2D fighting game, character faces RIGHT. "
        "{character}. "
        "2x2 grid with CLEAR BLACK BORDERS between 4 cells, each cell same size. "
        "Cell 1 (top-left): Jump CROUCH, squatting down before jump, knees deeply bent, "
        "arms pulling back for launch. "
        "Cell 2 (top-right): Jump RISING, body going up, legs tucking, arms raised. "
        "Cell 3 (bottom-left): Jump KICK, character in air, right leg extended forward "
        "in flying kick, body horizontal. "
        "Cell 4 (bottom-right): SPECIAL MOVE, character on ground, both hands thrust "
        "forward projecting a ball of blue lightning energy. "
        "All poses SIDE-VIEW like Street Fighter. "
        "Bright MAGENTA #FF00FF background in each cell. NOT green, NOT blue — pure magenta. "
        "Character centered and fully visible in each cell."
    ),

    "hurt_knockdown": (
        "Side-view pixel art sprite sheet for 2D fighting game, character faces RIGHT. "
        "{character}. "
        "2x2 grid with CLEAR BLACK BORDERS between 4 cells, each cell same size. "
        "Cell 1 (top-left): HIT REACTION, getting punched in face, head snapping back, "
        "body recoiling backward. "
        "Cell 2 (top-right): KNOCKDOWN, falling backward, body horizontal, "
        "arms flailing, about to hit ground. "
        "Cell 3 (bottom-left): ON GROUND, lying on back, fallen, defeated pose. "
        "Cell 4 (bottom-right): GETTING UP, rolling to one knee, "
        "pushing off ground to stand. "
        "All poses SIDE-VIEW like Street Fighter. "
        "Bright MAGENTA #FF00FF background in each cell. NOT green, NOT blue — pure magenta. "
        "Character centered and fully visible in each cell."
    ),
}


# ═══════════════════════════════════════════════════════════════════════
# IMAGE GENERATION
# ═══════════════════════════════════════════════════════════════════════

def generate_image(prompt: str, save_path: str) -> str:
    """Generate an image via fal.ai and save it. Returns the file path."""
    if not FAL_KEY:
        raise RuntimeError(
            "FAL_KEY environment variable not set. "
            "Get a key at fal.ai and set: export FAL_KEY=your_key_here"
        )

    url = "https://queue.fal.run/" + FAL_MODEL
    headers = {
        "Authorization": f"Key {FAL_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "prompt": prompt,
        "image_size": "square_hd",
        "num_images": 1,
        "enable_safety_checker": True,
    }

    # Submit
    resp = requests.post(url, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    request_id = resp.json()["request_id"]

    # Poll
    status_url = f"https://queue.fal.run/{FAL_MODEL}/requests/{request_id}"
    for _ in range(60):
        import time
        time.sleep(2)
        status_resp = requests.get(status_url, headers=headers, timeout=10)
        data = status_resp.json()
        if data.get("status") == "COMPLETED":
            image_url = data["images"][0]["url"]
            img_data = requests.get(image_url, timeout=30).content
            with open(save_path, "wb") as f:
                f.write(img_data)
            return save_path
        elif data.get("status") == "FAILED":
            raise RuntimeError(f"Generation failed: {data}")

    raise RuntimeError("Generation timed out")


def split_grid(image_path: str, cols: int = 2, rows: int = 2) -> list:
    """Split a grid image into individual cell images. Returns list of PIL Images."""
    img = Image.open(image_path).convert("RGBA")
    w, h = img.size
    cell_w, cell_h = w // cols, h // rows
    cells = []
    for r in range(rows):
        for c in range(cols):
            cell = img.crop((c * cell_w, r * cell_h, (c + 1) * cell_w, (r + 1) * cell_h))
            cells.append(cell)
    return cells


def chroma_key_and_crop(img: Image.Image, target_size=(96, 96), bg="magenta") -> Image.Image:
    """Remove background, crop tight, scale to fit, center in target."""
    arr = np.array(img)
    h, w = arr.shape[:2]

    def _is_bg(r, g, b):
        if bg == "green":
            return r < 80 and g > 160 and b < 80
        if bg == "blue":
            return r < 80 and g < 80 and b > 160
        return r > 200 and g < 50 and b > 200

    mask = np.zeros((h, w), dtype=bool)
    for y in range(h):
        for x in range(w):
            r, g, b = int(arr[y, x, 0]), int(arr[y, x, 1]), int(arr[y, x, 2])
            if not _is_bg(r, g, b):
                mask[y, x] = True

    if not np.any(mask):
        return Image.new("RGBA", target_size, (0, 0, 0, 0))

    rows_any = np.any(mask, axis=1)
    cols_any = np.any(mask, axis=0)
    rmin, rmax = np.where(rows_any)[0][[0, -1]]
    cmin, cmax = np.where(cols_any)[0][[0, -1]]
    pad = 8
    rmin = max(0, rmin - pad)
    cmin = max(0, cmin - pad)
    rmax = min(h - 1, rmax + pad)
    cmax = min(w - 1, cmax + pad)

    crop = img.crop((cmin, rmin, cmax + 1, rmax + 1)).convert("RGBA")
    crop_arr = np.array(crop)
    for y in range(crop_arr.shape[0]):
        for x in range(crop_arr.shape[1]):
            r, g, b = int(crop_arr[y, x, 0]), int(crop_arr[y, x, 1]), int(crop_arr[y, x, 2])
            if _is_bg(r, g, b):
                crop_arr[y, x, 3] = 0
    clean = Image.fromarray(crop_arr)

    cw, ch = clean.size
    if cw == 0 or ch == 0:
        return Image.new("RGBA", target_size, (0, 0, 0, 0))
    scale = min(target_size[0] / cw, target_size[1] / ch, 1.0)
    nw = max(1, int(cw * scale))
    nh = max(1, int(ch * scale))
    scaled = clean.resize((nw, nh), Image.NEAREST)

    result = Image.new("RGBA", target_size, (0, 0, 0, 0))
    px = (target_size[0] - nw) // 2
    py = (target_size[1] - nh) // 2
    result.paste(scaled, (px, py), scaled)
    return result


def assemble_sheet(frames_by_anim: dict, cell_size=(96, 96), gap=4) -> dict:
    """Assemble frames into a sprite sheet + hermes.json.

    frames_by_anim: { "idle": [PIL.Image, ...], "walk": [...], ... }
    Returns {"sheet_path": ..., "json_path": ..., "json_data": ...}
    """
    target_w, target_h = cell_size
    anims = list(frames_by_anim.keys())
    max_frames = max(len(v) for v in frames_by_anim.values())
    rows = len(anims)

    sheet_w = max_frames * (target_w + gap) + gap
    sheet_h = rows * (target_h + gap) + gap
    sheet = Image.new("RGBA", (sheet_w, sheet_h), (0, 0, 0, 0))

    animations = {}
    fps_map = {
        "idle": 6, "walk": 10, "punch": 15, "kick": 15,
        "jump": 12, "jump_kick": 12, "fireball": 10,
        "hurt": 12, "knockdown": 8, "getup": 8,
    }
    loop_map = {
        "idle": True, "walk": True, "punch": False, "kick": False,
        "jump": False, "jump_kick": False, "fireball": False,
        "hurt": False, "knockdown": False, "getup": False,
    }

    for row_idx, anim_name in enumerate(anims):
        frames = frames_by_anim[anim_name]
        y = gap + row_idx * (target_h + gap)
        rects = []
        for col_idx, frame in enumerate(frames):
            x = gap + col_idx * (target_w + gap)
            sheet.paste(frame, (x, y), frame)
            rects.append([x, y, target_w, target_h])
        animations[anim_name] = {
            "frames": rects,
            "fps": fps_map.get(anim_name, 10),
            "loop": loop_map.get(anim_name, False),
        }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sheet_path = os.path.join(OUTPUT_DIR, f"sprite_{timestamp}.png")
    json_path = os.path.join(OUTPUT_DIR, f"sprite_{timestamp}.json")
    sheet.save(sheet_path)

    json_data = {
        "version": 1,
        "sheet": os.path.basename(sheet_path),
        "size": [sheet_w, sheet_h],
        "bg_mode": "transparent",
        "animations": animations,
        "meta": {
            "source": "sprite_forge_app",
            "generated": timestamp,
            "total_frames": sum(len(v) for v in frames_by_anim.values()),
        },
    }
    with open(json_path, "w") as f:
        json.dump(json_data, f, indent=2)

    return {"sheet_path": sheet_path, "json_path": json_path, "json_data": json_data}


# ═══════════════════════════════════════════════════════════════════════
# STATIC FILE SERVING
# ═══════════════════════════════════════════════════════════════════════

@app.route("/ui.html")
def serve_ui():
    """Serve the self-contained UI."""
    ui_path = os.path.join(os.path.dirname(__file__), "ui.html")
    return render_template_string(open(ui_path, "r", encoding="utf-8").read())


@app.route("/")
def index():
    return serve_ui()


@app.route("/output/idle_walk_grid.png")
def serve_idle_walk():
    return send_file(os.path.join(OUTPUT_DIR, "idle_walk_grid.png"))


@app.route("/output/reference.png")
def serve_reference():
    return send_file(os.path.join(OUTPUT_DIR, "reference.png"))


@app.route("/output/latest.json")
def serve_latest():
    latest = os.path.join(OUTPUT_DIR, "latest.json")
    if os.path.exists(latest):
        return send_file(latest)
    return jsonify({"ready": False}), 404



@app.route("/api/upload", methods=["POST"])
def api_upload():
    """Save an uploaded image file."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if f.filename == "":
        return jsonify({"error": "No file selected"}), 400

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = os.path.splitext(f.filename)[1] or ".png"
    filename = f"upload_{timestamp}{ext}"
    save_path = os.path.join(OUTPUT_DIR, filename)
    f.save(save_path)

    # Return as base64
    with open(save_path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode()
    return jsonify({
        "success": True,
        "image": f"data:image/png;base64,{b64}",
        "path": save_path,
    })


@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.json
    step = data.get("step")
    character = data.get("character", "a fighter")

    if step not in PROMPTS:
        return jsonify({"error": f"Unknown step: {step}"}), 400

    prompt = PROMPTS[step].format(character=character)
    filename = f"{step}_{hashlib.md5(prompt.encode()).hexdigest()[:8]}.png"
    save_path = os.path.join(OUTPUT_DIR, filename)

    try:
        generate_image(prompt, save_path)
        # Return the image as base64 for inline display
        with open(save_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return jsonify({
            "success": True,
            "image": f"data:image/png;base64,{b64}",
            "path": save_path,
            "prompt": prompt,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/split", methods=["POST"])
def api_split():
    """Split a grid image into cells and return them as base64."""
    data = request.json
    image_path = data.get("path")
    cols = data.get("cols", 2)
    rows = data.get("rows", 2)

    if not image_path or not os.path.exists(image_path):
        return jsonify({"error": "Image not found"}), 400

    cells = split_grid(image_path, cols, rows)
    result = []
    for i, cell in enumerate(cells):
        # Process: chroma key + crop
        processed = chroma_key_and_crop(cell)
        # Save processed cell
        cell_path = image_path.replace(".png", f"_cell_{i}.png")
        processed.save(cell_path)
        # Return as base64
        import io
        buf = io.BytesIO()
        processed.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        result.append({"index": i, "image": f"data:image/png;base64,{b64}", "path": cell_path})

    return jsonify({"success": True, "cells": result})


@app.route("/api/assemble", methods=["POST"])
def api_assemble():
    """Assemble approved frames into a final sprite sheet."""
    data = request.json
    frames_by_anim = {}

    for anim_name, frame_paths in data.get("animations", {}).items():
        frames = []
        for p in frame_paths:
            if os.path.exists(p):
                img = Image.open(p).convert("RGBA")
                # Re-process to ensure consistent sizing
                processed = chroma_key_and_crop(img)
                frames.append(processed)
        if frames:
            frames_by_anim[anim_name] = frames

    if not frames_by_anim:
        return jsonify({"error": "No frames to assemble"}), 400

    result = assemble_sheet(frames_by_anim)

    # Return sheet as base64 for preview
    with open(result["sheet_path"], "rb") as f:
        sheet_b64 = base64.b64encode(f.read()).decode()

    return jsonify({
        "success": True,
        "sheet": f"data:image/png;base64,{sheet_b64}",
        "sheet_path": result["sheet_path"],
        "json_path": result["json_path"],
        "json_data": result["json_data"],
    })


@app.route("/api/download/<path:filename>")
def api_download(filename):
    """Download a generated file."""
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(path):
        return "Not found", 404
    return send_file(path, as_attachment=True)


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 50)
    print("  Sprite Forge — 2D Fighter Generator")
    print("=" * 50)
    print(f"  Open: http://localhost:5001")
    print(f"  Output: {OUTPUT_DIR}")
    if not FAL_KEY:
        print(f"  ⚠ FAL_KEY not set — set it with:")
        print(f"    export FAL_KEY=your_key_here")
    else:
        print(f"  ✓ FAL_KEY configured")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5001, debug=False)
