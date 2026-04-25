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
# API ROUTES
# ═══════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template_string(UI_HTML)



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
# UI (embedded HTML)
# ═══════════════════════════════════════════════════════════════════════

UI_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sprite Forge — 2D Fighter Generator</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'Courier New', Courier, monospace;
  background: #0a0a0a; color: #d8d8d8;
  min-height: 100vh; padding: 20px;
}
.page { display: none; max-width: 900px; margin: 0 auto; }
.page.active { display: block; }

h1 { color: #7af; font-size: 28px; margin-bottom: 8px; }
h2 { color: #7af; font-size: 20px; margin-bottom: 12px;
     border-bottom: 1px solid #333; padding-bottom: 8px; }
p { color: #aaa; line-height: 1.6; margin-bottom: 12px; font-size: 14px; }
b { color: #ddd; }

.btn {
  background: #1a2a3a; color: #7af; border: 1px solid #357;
  padding: 10px 24px; font-family: inherit; font-size: 14px;
  cursor: pointer; border-radius: 4px; margin: 4px;
  transition: background 0.2s;
}
.btn:hover { background: #253545; border-color: #5af; }
.btn.primary {
  background: #1a3a2a; border-color: #3a6; color: #afa; font-weight: bold;
}
.btn.primary:hover { background: #254a35; }
.btn.danger {
  background: #3a1a1a; border-color: #a33; color: #faa;
}
.btn.danger:hover { background: #4a2525; }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }

input[type="text"], textarea {
  background: #111; color: #ddd; border: 1px solid #333;
  padding: 10px 14px; font-family: inherit; font-size: 14px;
  border-radius: 4px; width: 100%;
}
input[type="text"]:focus, textarea:focus {
  border-color: #555; outline: none;
}

/* Drop zone */
.dropzone {
  border: 3px dashed #444; border-radius: 12px;
  padding: 40px; text-align: center;
  background: #111; cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
  margin: 16px 0;
}
.dropzone:hover, .dropzone.dragover {
  border-color: #7af; background: #151820;
}
.dropzone .icon { font-size: 48px; margin-bottom: 12px; }
.dropzone .label { color: #7af; font-size: 16px; }
.dropzone .hint { color: #555; font-size: 12px; margin-top: 6px; }

/* Image preview */
.preview-container {
  display: flex; gap: 20px; margin: 16px 0;
  align-items: flex-start; flex-wrap: wrap;
}
.preview-img {
  border: 2px solid #333; border-radius: 4px;
  image-rendering: pixelated;
  max-width: 100%;
}
.preview-img.approved { border-color: #3a6; box-shadow: 0 0 8px rgba(50,170,100,0.4); }
.preview-img.rejected { border-color: #a33; box-shadow: 0 0 8px rgba(170,50,50,0.4); }

/* Cell grid */
.cell-grid {
  display: flex; flex-wrap: wrap; gap: 8px; margin: 16px 0;
}
.cell-card {
  border: 2px solid #333; border-radius: 4px;
  background: #151515; cursor: pointer;
  padding: 0; overflow: hidden;
  transition: border-color 0.15s;
  position: relative;
}
.cell-card:hover { border-color: #555; }
.cell-card.selected { border-color: #7af; }
.cell-card.good { border-color: #3a6; }
.cell-card.bad { border-color: #a33; }
.cell-card canvas {
  display: block; image-rendering: pixelated;
}
.cell-card .label {
  padding: 3px 5px; font-size: 10px; color: #888;
  background: #111; border-top: 1px solid #222;
}
.cell-card .badge {
  position: absolute; top: 2px; right: 2px;
  font-size: 16px; font-weight: bold;
  text-shadow: 0 0 4px #000;
}

/* Status bar */
.status-bar {
  display: flex; gap: 16px; flex-wrap: wrap;
  background: #111; border: 1px solid #222; border-radius: 4px;
  padding: 8px 14px; margin: 12px 0; font-size: 13px;
}
.status-bar .stat .val { color: #7af; font-weight: bold; }

/* Spinner */
.spinner {
  display: inline-block; width: 20px; height: 20px;
  border: 2px solid #333; border-top-color: #7af;
  border-radius: 50%; animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.loading { text-align: center; padding: 40px; color: #7af; }
.loading .spinner { width: 40px; height: 40px; margin-bottom: 12px; }

/* Navigation */
.nav-bar {
  display: flex; justify-content: space-between;
  margin-top: 20px; padding-top: 16px;
  border-top: 1px solid #222;
}

/* Step indicator */
.steps {
  display: flex; gap: 8px; margin-bottom: 20px;
}
.step-dot {
  width: 10px; height: 10px; border-radius: 50%;
  background: #222; border: 1px solid #444;
}
.step-dot.active { background: #7af; border-color: #7af; }
.step-dot.done { background: #3a6; border-color: #3a6; }

/* Anim label input */
.anim-input {
  background: #0a0a0a; color: #ccc; border: 1px solid #333;
  padding: 3px 8px; font-family: inherit; font-size: 12px;
  border-radius: 3px; width: 100px; margin-bottom: 4px;
}

.section { margin: 16px 0; }
.flex-row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.mt-8 { margin-top: 8px; }
.mt-16 { margin-top: 16px; }
.mb-8 { margin-bottom: 8px; }
.hidden { display: none !important; }
</style>
</head>
<body>

<!-- ═══════════ STEP INDICATOR ═══════════ -->
<div class="steps" id="steps">
  <div class="step-dot active" data-step="0"></div>
  <div class="step-dot" data-step="1"></div>
  <div class="step-dot" data-step="2"></div>
  <div class="step-dot" data-step="3"></div>
  <div class="step-dot" data-step="4"></div>
  <div class="step-dot" data-step="5"></div>
  <div class="step-dot" data-step="6"></div>
</div>

<!-- ═══════════ PAGE 0: WELCOME ═══════════ -->
<div class="page active" id="page-0">
  <h1>⚡ Sprite Forge</h1>
  <h2>2D Fighter Sprite Sheet Generator</h2>
  <p>
    Welcome to Sprite Forge — a tool that generates complete sprite sheets
    for 2D fighting game characters using AI.
  </p>
  <p>
    You'll walk through <b>7 steps</b>: describe your character, approve a
    reference image, then generate and review animations for <b>idle/walk</b>,
    <b>punch/kick</b>, <b>jump/special</b>, and <b>hit reactions</b>.
    At each step you pick the good frames and reject the bad ones.
  </p>
  <p>
    When you're done, you get a <b>sprite sheet PNG</b> + a <b>JSON file</b>
    that any game engine can load.
  </p>
  <p>
    All sprites are generated <b>side-facing</b> (like Street Fighter)
    on a <b style="color:#f0f">magenta background</b>, then automatically cropped and assembled.
    Magenta works for any character color — even green or blue.
  </p>
  <div class="nav-bar">
    <div></div>
    <button class="btn primary" onclick="goTo(1)">Start →</button>
  </div>
</div>

<!-- ═══════════ PAGE 1: CHARACTER PROMPT ═══════════ -->
<div class="page" id="page-1">
  <h2>Step 1: Create Your Character</h2>
  <p>Choose one: <b>describe</b> your character and we'll generate a reference image,
     or <b>upload an image</b> you already have.</p>

  <div style="display:flex; gap:20px; flex-wrap:wrap; margin-top:16px;">

    <!-- Left: Text prompt -->
    <div style="flex:1; min-width:280px;">
      <h3 style="color:#7af; margin-bottom:8px;">✏️ Describe Character</h3>
      <textarea id="charPrompt" rows="4" placeholder="Example: Zeus, muscular Greek god with long white beard, white hair in ponytail, golden chest armor with eagle medallion, blue loincloth, leather belt, brown sandals"></textarea>
      <button class="btn primary mt-8" onclick="generateReference()">Generate Reference →</button>
    </div>

    <!-- Right: Image upload -->
    <div style="flex:1; min-width:280px;">
      <h3 style="color:#7af; margin-bottom:8px;">🖼️ Or Upload Image</h3>
      <div class="dropzone" id="uploadDropzone"
           ondragover="event.preventDefault(); this.classList.add('dragover');"
           ondragleave="this.classList.remove('dragover');"
           ondrop="event.preventDefault(); this.classList.remove('dragover'); handleUpload(event.dataTransfer.files[0]);">
        <div class="icon">📁</div>
        <div class="label">Drop image here</div>
        <div class="hint">or click to browse · or paste from clipboard (Ctrl+V)</div>
        <input type="file" id="uploadInput" accept="image/*" style="display:none"
               onchange="handleUpload(this.files[0]);">
      </div>
    </div>
  </div>

  <div id="refLoading" class="loading hidden">
    <div class="spinner"></div>
    <p>Generating reference image... this takes 10-20 seconds</p>
  </div>

  <div id="refPreview" class="hidden">
    <h3 class="mt-16">Reference Image</h3>
    <div class="preview-container">
      <img id="refImage" class="preview-img" style="max-width:300px;">
    </div>
    <p>Does this look right? Side-facing, fighting stance?</p>
    <div class="flex-row mt-8">
      <button class="btn primary" onclick="approveReference()">✓ Looks Good, Continue</button>
      <button class="btn danger" onclick="resetReference()">✗ Start Over</button>
    </div>
  </div>

  <div class="nav-bar">
    <button class="btn" onclick="goTo(0)">← Back</button>
  </div>
</div>

<!-- ═══════════ PAGE 2: IDLE + WALK ═══════════ -->
<div class="page" id="page-2">
  <h2>Step 2: Idle & Walk Animations</h2>
  <p>Generating a 2×2 grid: <b>idle stance</b> + <b>3 walk cycle frames</b>.
     Click frames to mark <b style="color:#7c7">good (G)</b> or
     <b style="color:#faa">bad (B)</b>. Bad frames will be regenerated.</p>
  <button class="btn primary" onclick="generateStep('idle_walk')">Generate Idle + Walk</button>
  <div id="idleWalkLoading" class="loading hidden">
    <div class="spinner"></div><p>Generating...</p>
  </div>
  <div id="idleWalkCells" class="hidden">
    <div class="status-bar" id="idleWalkStatus"></div>
    <div class="cell-grid" id="idleWalkGrid"></div>
    <div class="flex-row mt-8">
      <input class="anim-input" id="iw0" value="idle" placeholder="anim name">
      <input class="anim-input" id="iw1" value="walk" placeholder="anim name">
      <input class="anim-input" id="iw2" value="walk" placeholder="anim name">
      <input class="anim-input" id="iw3" value="walk" placeholder="anim name">
    </div>
    <div class="flex-row mt-8">
      <button class="btn primary" onclick="approveStep('idleWalk')">✓ Accept & Continue</button>
      <button class="btn" onclick="generateStep('idle_walk')">↻ Regenerate All</button>
    </div>
  </div>
  <div class="nav-bar">
    <button class="btn" onclick="goTo(1)">← Back</button>
  </div>
</div>

<!-- ═══════════ PAGE 3: PUNCH + KICK ═══════════ -->
<div class="page" id="page-3">
  <h2>Step 3: Punch & Kick Animations</h2>
  <p>Generating: <b>punch wind-up</b>, <b>punch extension</b>,
     <b>kick chamber</b>, <b>kick extension</b>.</p>
  <button class="btn primary" onclick="generateStep('punch_kick')">Generate Punch + Kick</button>
  <div id="punchKickLoading" class="loading hidden">
    <div class="spinner"></div><p>Generating...</p>
  </div>
  <div id="punchKickCells" class="hidden">
    <div class="status-bar" id="punchKickStatus"></div>
    <div class="cell-grid" id="punchKickGrid"></div>
    <div class="flex-row mt-8">
      <input class="anim-input" id="pk0" value="punch" placeholder="anim name">
      <input class="anim-input" id="pk1" value="punch" placeholder="anim name">
      <input class="anim-input" id="pk2" value="kick" placeholder="anim name">
      <input class="anim-input" id="pk3" value="kick" placeholder="anim name">
    </div>
    <div class="flex-row mt-8">
      <button class="btn primary" onclick="approveStep('punchKick')">✓ Accept & Continue</button>
      <button class="btn" onclick="generateStep('punch_kick')">↻ Regenerate All</button>
    </div>
  </div>
  <div class="nav-bar">
    <button class="btn" onclick="goTo(2)">← Back</button>
  </div>
</div>

<!-- ═══════════ PAGE 4: JUMP + SPECIAL ═══════════ -->
<div class="page" id="page-4">
  <h2>Step 4: Jump & Special Move</h2>
  <p>Generating: <b>jump crouch</b>, <b>jump rise</b>,
     <b>jump kick</b>, <b>projectile blast</b>.</p>
  <button class="btn primary" onclick="generateStep('jump_special')">Generate Jump + Special</button>
  <div id="jumpSpecialLoading" class="loading hidden">
    <div class="spinner"></div><p>Generating...</p>
  </div>
  <div id="jumpSpecialCells" class="hidden">
    <div class="status-bar" id="jumpSpecialStatus"></div>
    <div class="cell-grid" id="jumpSpecialGrid"></div>
    <div class="flex-row mt-8">
      <input class="anim-input" id="js0" value="jump" placeholder="anim name">
      <input class="anim-input" id="js1" value="jump" placeholder="anim name">
      <input class="anim-input" id="js2" value="jump_kick" placeholder="anim name">
      <input class="anim-input" id="js3" value="fireball" placeholder="anim name">
    </div>
    <div class="flex-row mt-8">
      <button class="btn primary" onclick="approveStep('jumpSpecial')">✓ Accept & Continue</button>
      <button class="btn" onclick="generateStep('jump_special')">↻ Regenerate All</button>
    </div>
  </div>
  <div class="nav-bar">
    <button class="btn" onclick="goTo(3)">← Back</button>
  </div>
</div>

<!-- ═══════════ PAGE 5: HIT REACTIONS ═══════════ -->
<div class="page" id="page-5">
  <h2>Step 5: Hit Reactions</h2>
  <p>Generating: <b>hit reaction</b>, <b>knockdown</b>,
     <b>on ground</b>, <b>getting up</b>.</p>
  <button class="btn primary" onclick="generateStep('hurt_knockdown')">Generate Hit Reactions</button>
  <div id="hurtKnockdownLoading" class="loading hidden">
    <div class="spinner"></div><p>Generating...</p>
  </div>
  <div id="hurtKnockdownCells" class="hidden">
    <div class="status-bar" id="hurtKnockdownStatus"></div>
    <div class="cell-grid" id="hurtKnockdownGrid"></div>
    <div class="flex-row mt-8">
      <input class="anim-input" id="hk0" value="hurt" placeholder="anim name">
      <input class="anim-input" id="hk1" value="knockdown" placeholder="anim name">
      <input class="anim-input" id="hk2" value="knockdown" placeholder="anim name">
      <input class="anim-input" id="hk3" value="getup" placeholder="anim name">
    </div>
    <div class="flex-row mt-8">
      <button class="btn primary" onclick="approveStep('hurtKnockdown')">✓ Build Final Sheet</button>
      <button class="btn" onclick="generateStep('hurt_knockdown')">↻ Regenerate All</button>
    </div>
  </div>
  <div class="nav-bar">
    <button class="btn" onclick="goTo(4)">← Back</button>
  </div>
</div>

<!-- ═══════════ PAGE 6: FINAL SHEET ═══════════ -->
<div class="page" id="page-6">
  <h2>⚡ Sprite Sheet Complete!</h2>
  <div id="finalLoading" class="loading">
    <div class="spinner"></div><p>Assembling sprite sheet...</p>
  </div>
  <div id="finalResult" class="hidden">
    <p>Your sprite sheet is ready. <b id="finalStats"></b></p>
    <div class="preview-container mt-16">
      <img id="finalSheet" class="preview-img" style="max-width:100%; border-color:#3a6;">
    </div>
    <div class="flex-row mt-16">
      <button class="btn primary" id="btnDownloadSheet" onclick="downloadFile('sheet')">⬇ Download Sheet (PNG)</button>
      <button class="btn primary" id="btnDownloadJson" onclick="downloadFile('json')">⬇ Download JSON</button>
    </div>
    <div class="mt-16">
      <h3>Animations</h3>
      <div id="finalAnims" class="mt-8"></div>
    </div>
    <div class="mt-16">
      <button class="btn" onclick="location.reload()">↻ Start Over</button>
    </div>
  </div>
</div>

<script>
// ═══════════════════════════════════════════════════════════════════
// STATE
// ═══════════════════════════════════════════════════════════════════

let character = '';
let currentStep = 0;
let approvedFrames = {};   // stepName -> [{path, animName, status}]
let cellPaths = {};         // stepName -> [path, path, ...]
let finalSheetPath = '';
let finalJsonPath = '';

// ═══════════════════════════════════════════════════════════════════
// NAVIGATION
// ═══════════════════════════════════════════════════════════════════

function goTo(page) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById('page-' + page).classList.add('active');
  currentStep = page;
  updateStepDots();
}

function updateStepDots() {
  document.querySelectorAll('.step-dot').forEach((dot, i) => {
    dot.classList.remove('active', 'done');
    if (i === currentStep) dot.classList.add('active');
    else if (i < currentStep) dot.classList.add('done');
  });
}

// ═══════════════════════════════════════════════════════════════════
// GENERATION
// ═══════════════════════════════════════════════════════════════════


// ═══════════════════════════════════════════════════════════════════
// FILE UPLOAD
// ═══════════════════════════════════════════════════════════════════

document.getElementById('uploadDropzone').onclick = () => {
  document.getElementById('uploadInput').click();
};

async function handleUpload(file) {
  if (!file || !file.type.startsWith('image/')) {
    alert('Please drop or select an image file.'); return;
  }
  const formData = new FormData();
  formData.append('file', file);

  document.getElementById('refLoading').classList.remove('hidden');
  document.getElementById('refPreview').classList.add('hidden');

  try {
    const resp = await fetch('/api/upload', { method: 'POST', body: formData });
    const data = await resp.json();
    document.getElementById('refLoading').classList.add('hidden');
    if (data.error) { alert('Error: ' + data.error); return; }
    document.getElementById('refImage').src = data.image;
    document.getElementById('refPreview').classList.remove('hidden');
    cellPaths._reference = data.path;
    // Hide the input sections since we have a reference
    document.getElementById('uploadDropzone').style.opacity = '0.4';
    document.getElementById('uploadDropzone').style.pointerEvents = 'none';
  } catch (e) {
    document.getElementById('refLoading').classList.add('hidden');
    alert('Upload failed: ' + e.message);
  }
}

// Paste from clipboard
document.addEventListener('paste', (e) => {
  if (currentStep !== 1) return;
  const items = e.clipboardData?.items;
  if (!items) return;
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      e.preventDefault();
      handleUpload(item.getAsFile());
      return;
    }
  }
});

function resetReference() {
  document.getElementById('refPreview').classList.add('hidden');
  document.getElementById('refImage').src = '';
  cellPaths._reference = null;
  document.getElementById('uploadDropzone').style.opacity = '1';
  document.getElementById('uploadDropzone').style.pointerEvents = 'auto';
}

async function generateReference() {
  character = document.getElementById('charPrompt').value.trim();
  if (!character) { alert('Please describe your character first.'); return; }

  document.getElementById('refLoading').classList.remove('hidden');
  document.getElementById('refPreview').classList.add('hidden');

  const resp = await api('generate', { step: 'reference', character });
  document.getElementById('refLoading').classList.add('hidden');

  if (resp.error) { alert('Error: ' + resp.error); return; }

  document.getElementById('refImage').src = resp.image;
  document.getElementById('refPreview').classList.remove('hidden');
  cellPaths._reference = resp.path;
}

function approveReference() {
  goTo(2);
}

const STEP_MAP = {
  idleWalk: 'idle_walk',
  punchKick: 'punch_kick',
  jumpSpecial: 'jump_special',
  hurtKnockdown: 'hurt_knockdown',
};

async function generateStep(stepKey) {
  const realStep = STEP_MAP[stepKey] || stepKey;
  const loadingId = stepKey.charAt(0).toLowerCase() + stepKey.slice(1) + 'Loading';
  const cellsId = stepKey.charAt(0).toLowerCase() + stepKey.slice(1) + 'Cells';
  const gridId = stepKey.charAt(0).toLowerCase() + stepKey.slice(1) + 'Grid';

  // Show loading
  const loadingEl = document.getElementById(
    stepKey === 'idleWalk' ? 'idleWalkLoading' :
    stepKey === 'punchKick' ? 'punchKickLoading' :
    stepKey === 'jumpSpecial' ? 'jumpSpecialLoading' :
    'hurtKnockdownLoading'
  );
  const cellsEl = document.getElementById(
    stepKey === 'idleWalk' ? 'idleWalkCells' :
    stepKey === 'punchKick' ? 'punchKickCells' :
    stepKey === 'jumpSpecial' ? 'jumpSpecialCells' :
    'hurtKnockdownCells'
  );
  const gridEl = document.getElementById(
    stepKey === 'idleWalk' ? 'idleWalkGrid' :
    stepKey === 'punchKick' ? 'punchKickGrid' :
    stepKey === 'jumpSpecial' ? 'jumpSpecialGrid' :
    'hurtKnockdownGrid'
  );

  loadingEl.classList.remove('hidden');
  cellsEl.classList.add('hidden');

  const resp = await api('generate', { step: realStep, character });
  if (resp.error) { alert('Error: ' + resp.error); loadingEl.classList.add('hidden'); return; }

  const splitResp = await api('split', { path: resp.path, cols: 2, rows: 2 });
  loadingEl.classList.add('hidden');

  if (splitResp.error) { alert('Error: ' + splitResp.error); return; }

  cellPaths[stepKey] = splitResp.cells.map(c => c.path);
  renderCells(gridEl, splitResp.cells, stepKey);
  updateStatus(stepKey);
  cellsEl.classList.remove('hidden');
}

function renderCells(gridEl, cells, stepKey) {
  gridEl.innerHTML = '';
  cells.forEach((cell, i) => {
    const card = document.createElement('div');
    card.className = 'cell-card';
    card.dataset.step = stepKey;
    card.dataset.index = i;
    card.dataset.status = 'unmarked';

    const canvas = document.createElement('canvas');
    const img = new Image();
    img.onload = () => {
      // Display at 4x
      const scale = 4;
      canvas.width = img.width * scale;
      canvas.height = img.height * scale;
      canvas.style.width = canvas.width + 'px';
      canvas.style.height = canvas.height + 'px';
      const ctx = canvas.getContext('2d');
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    };
    img.src = cell.image;

    const label = document.createElement('div');
    label.className = 'label';
    label.textContent = `Frame ${i}`;

    const badge = document.createElement('div');
    badge.className = 'badge';

    card.appendChild(canvas);
    card.appendChild(badge);
    card.appendChild(label);

    card.onclick = () => toggleCell(card);
    gridEl.appendChild(card);
  });
}

function toggleCell(card) {
  document.querySelectorAll('.cell-card').forEach(c => c.classList.remove('selected'));
  card.classList.add('selected');
  const status = card.dataset.status;
  if (status === 'unmarked' || status === 'rejected') {
    card.dataset.status = 'good';
    card.classList.remove('bad');
    card.classList.add('good');
    card.querySelector('.badge').textContent = '✓';
  } else {
    card.dataset.status = 'rejected';
    card.classList.remove('good');
    card.classList.add('bad');
    card.querySelector('.badge').textContent = '✗';
  }
  updateStatus(card.dataset.step);
}

function updateStatus(stepKey) {
  const gridId = stepKey === 'idleWalk' ? 'idleWalkGrid' :
                 stepKey === 'punchKick' ? 'punchKickGrid' :
                 stepKey === 'jumpSpecial' ? 'jumpSpecialGrid' :
                 'hurtKnockdownGrid';
  const statusId = stepKey === 'idleWalk' ? 'idleWalkStatus' :
                   stepKey === 'punchKick' ? 'punchKickStatus' :
                   stepKey === 'jumpSpecial' ? 'jumpSpecialStatus' :
                   'hurtKnockdownStatus';

  const cards = document.querySelectorAll(`#${gridId} .cell-card`);
  let good = 0, bad = 0, unmarked = 0;
  cards.forEach(c => {
    if (c.dataset.status === 'good') good++;
    else if (c.dataset.status === 'rejected') bad++;
    else unmarked++;
  });

  document.getElementById(statusId).innerHTML = `
    <div class="stat">Frames: <span class="val">${cards.length}</span></div>
    <div class="stat">Good: <span class="val" style="color:#7c7">${good}</span></div>
    <div class="stat">Bad: <span class="val" style="color:#faa">${bad}</span></div>
    <div class="stat">Unmarked: <span class="val" style="color:#aa7">${unmarked}</span></div>
  `;
}

// ═══════════════════════════════════════════════════════════════════
// APPROVAL & ASSEMBLY
// ═══════════════════════════════════════════════════════════════════

function approveStep(stepKey) {
  // Collect approved frames with their animation names
  const gridId = stepKey === 'idleWalk' ? 'idleWalkGrid' :
                 stepKey === 'punchKick' ? 'punchKickGrid' :
                 stepKey === 'jumpSpecial' ? 'jumpSpecialGrid' :
                 'hurtKnockdownGrid';
  const prefix = stepKey === 'idleWalk' ? 'iw' :
                 stepKey === 'punchKick' ? 'pk' :
                 stepKey === 'jumpSpecial' ? 'js' : 'hk';

  const cards = document.querySelectorAll(`#${gridId} .cell-card`);
  const paths = cellPaths[stepKey] || [];
  const frames = [];

  cards.forEach((card, i) => {
    const status = card.dataset.status === 'good' ? 'good' : 'keep';
    const animInput = document.getElementById(prefix + i);
    const animName = animInput ? animInput.value : 'unknown';
    frames.push({ path: paths[i], anim: animName, status });
  });

  approvedFrames[stepKey] = frames;

  // Navigate to next step
  const nextStep = {
    idleWalk: 3,
    punchKick: 4,
    jumpSpecial: 5,
    hurtKnockdown: 6,
  };
  const next = nextStep[stepKey];
  if (next === 6) {
    goTo(6);
    buildFinalSheet();
  } else {
    goTo(next);
  }
}

async function buildFinalSheet() {
  document.getElementById('finalLoading').classList.remove('hidden');
  document.getElementById('finalResult').classList.add('hidden');

  // Merge all approved frames, grouped by animation
  const animFrames = {};
  for (const [stepKey, frames] of Object.entries(approvedFrames)) {
    for (const frame of frames) {
      if (!animFrames[frame.anim]) animFrames[frame.anim] = [];
      animFrames[frame.anim].push(frame.path);
    }
  }

  const resp = await api('assemble', { animations: animFrames });
  document.getElementById('finalLoading').classList.add('hidden');

  if (resp.error) { alert('Error: ' + resp.error); return; }

  document.getElementById('finalSheet').src = resp.sheet;
  document.getElementById('finalStats').textContent =
    `${resp.json_data.meta.total_frames} frames across ${Object.keys(resp.json_data.animations).length} animations`;
  finalSheetPath = resp.sheet_path;
  finalJsonPath = resp.json_path;

  // List animations
  const animsDiv = document.getElementById('finalAnims');
  animsDiv.innerHTML = '';
  for (const [name, anim] of Object.entries(resp.json_data.animations)) {
    const div = document.createElement('div');
    div.style.marginBottom = '4px';
    div.innerHTML = `<b style="color:#7af">${name}</b>: ${anim.frames.length} frames, ${anim.fps}fps, ${anim.loop ? 'loop' : 'once'}`;
    animsDiv.appendChild(div);
  }

  document.getElementById('finalResult').classList.remove('hidden');
}

function downloadFile(type) {
  const path = type === 'sheet' ? finalSheetPath : finalJsonPath;
  const filename = path.split('/').pop();
  window.open(`/api/download/${filename}`, '_blank');
}

// ═══════════════════════════════════════════════════════════════════
// API HELPER
// ═══════════════════════════════════════════════════════════════════

async function api(endpoint, data) {
  try {
    const resp = await fetch(`/api/${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return await resp.json();
  } catch (e) {
    return { error: e.message };
  }
}

// Keyboard shortcuts
document.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  if (e.key === 'g' || e.key === 'G') {
    document.querySelectorAll('.cell-card.selected').forEach(c => {
      c.dataset.status = 'good'; c.classList.remove('bad'); c.classList.add('good');
      c.querySelector('.badge').textContent = '✓';
    });
  }
  if (e.key === 'b' || e.key === 'B') {
    document.querySelectorAll('.cell-card.selected').forEach(c => {
      c.dataset.status = 'rejected'; c.classList.remove('good'); c.classList.add('bad');
      c.querySelector('.badge').textContent = '✗';
    });
  }
});
</script>
</body>
</html>
"""

# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 50)
    print("  Sprite Forge — 2D Fighter Generator")
    print("=" * 50)
    print(f"  Open: http://localhost:5000")
    print(f"  Output: {OUTPUT_DIR}")
    if not FAL_KEY:
        print(f"  ⚠ FAL_KEY not set — set it with:")
        print(f"    export FAL_KEY=your_key_here")
    else:
        print(f"  ✓ FAL_KEY configured")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=False)
