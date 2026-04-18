#!/usr/bin/env python3
"""
Sprite Forge Generator — multi-backend sprite sheet creation.

Three backends:
  1. 'image_gen'  — calls the caller's image generator hook (default path).
                    Hermes Agent's built-in image_generate tool works here.
  2. 'ascii'      — pyfiglet + PIL. Renders big ASCII glyphs, snapshots, chroma-keys.
                    Free, offline, retro aesthetic. No API keys.
  3. 'fal'        — fal.ai nano-banana backend. STUB until you add credit.

Callers decide which backend via the `backend` arg. No backend here
makes real API calls on its own — the image_gen backend takes a
callable the caller supplies so Hermes Agent can wire in its
image_generate tool without this module importing it.

Usage:
    from generator import generate_strip, generate_sheet_from_template

    # Pass your own image-generation callable
    def my_gen(prompt, aspect_ratio='landscape'):
        # Return path to a generated PNG
        ...

    strip = generate_strip(
        prompt="idle pose, 4 frames, character centered, green bg",
        backend='image_gen',
        image_gen_callable=my_gen,
        out_path='/tmp/idle_strip.png',
    )
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

try:
    import pyfiglet
    HAS_PYFIGLET = True
except ImportError:
    HAS_PYFIGLET = False


# --- Backend types ---------------------------------------------------

ImageGenCallable = Callable[..., str]
"""Signature: (prompt: str, **kwargs) -> path_to_generated_png"""


# --- Prompt helpers --------------------------------------------------

# Every strip prompt is built from a base + style + animation spec.
# The base is boilerplate that makes AI image gen produce clean grids.
STRIP_PROMPT_BASE = (
    "sprite sheet strip, {n_frames} frames side by side, "
    "each frame exactly {cell_w}x{cell_h} pixels, "
    "10px gap between frames, "
    "character centered in each frame, "
    "limbs and effects contained within frame boundaries, "
    "bright green chroma-key background #00FF00, "
    "pixel art style, "
)


def build_strip_prompt(
    animation: str,
    n_frames: int = 4,
    cell_w: int = 96,
    cell_h: int = 96,
    character_desc: str = "",
    style_desc: str = "16-bit pixel art",
    extra_instructions: str = "",
) -> str:
    """Compose a strip prompt from the standard template."""
    base = STRIP_PROMPT_BASE.format(
        n_frames=n_frames, cell_w=cell_w, cell_h=cell_h,
    )
    parts = [base, style_desc]
    if character_desc:
        parts.append(f"character: {character_desc}")
    parts.append(f"animation: {animation}")
    if extra_instructions:
        parts.append(extra_instructions)
    return ", ".join(parts)


# --- Backend 1: image_gen (delegated to caller's tool) ---------------

def _generate_via_image_gen(
    prompt: str,
    image_gen_callable: ImageGenCallable,
    out_path: str,
    aspect_ratio: str = "landscape",
) -> str:
    """Call caller's image generation function, save/copy to out_path.

    The callable is expected to return a path to a generated PNG.
    We copy that PNG to out_path so callers get a predictable location.
    """
    if image_gen_callable is None:
        raise ValueError(
            "backend='image_gen' requires image_gen_callable. Pass a function "
            "with signature (prompt: str, **kw) -> path_to_png. Hermes Agent's "
            "built-in image_generate tool satisfies this."
        )
    generated_path = image_gen_callable(prompt, aspect_ratio=aspect_ratio)
    if not generated_path or not os.path.exists(generated_path):
        raise RuntimeError(
            f"image_gen_callable returned invalid path: {generated_path!r}"
        )
    if os.path.abspath(generated_path) != os.path.abspath(out_path):
        shutil.copy(generated_path, out_path)
    return out_path


# --- Backend 2: ASCII (pyfiglet + PIL) -------------------------------

def _generate_via_ascii(
    animation: str,
    n_frames: int,
    cell_w: int,
    cell_h: int,
    character_desc: str,
    out_path: str,
    font: str = "standard",
) -> str:
    """Render an ASCII-art sprite strip.

    The trick: we take a short character-identifying string (derived from
    character_desc or animation), render it as BIG ASCII via pyfiglet,
    snapshot it into a PIL canvas with a bright-green background, and
    lay out n_frames side by side with slight per-frame variations so
    the strip reads as an animation.
    """
    if not HAS_PYFIGLET:
        raise RuntimeError(
            "ASCII backend requires pyfiglet. Install: pip install pyfiglet"
        )

    # Pick a short identifier to render. If the caller gave us
    # "cat fighter", we use "CAT". If just "punch", we use ">P<" etc.
    ident = _ascii_ident_from_desc(character_desc or animation)

    # Try a few fonts, fall back on failure
    fonts_to_try = [font, "standard", "small", "mini"]
    fig = None
    for f in fonts_to_try:
        try:
            fig = pyfiglet.Figlet(font=f, width=200)
            break
        except Exception:
            continue
    if fig is None:
        raise RuntimeError("pyfiglet: no usable font found")

    rendered = fig.renderText(ident).rstrip("\n")
    if not rendered.strip():
        rendered = ident

    # Tiny per-frame variations to sell it as animation:
    # rotate/shift the identifier or append a motion glyph per frame.
    motion_glyphs = _motion_glyphs_for(animation)

    # Build the strip PNG
    strip_w = n_frames * cell_w + (n_frames - 1) * 10
    strip_h = cell_h
    strip = Image.new("RGBA", (strip_w, strip_h), (0, 255, 0, 255))
    draw = ImageDraw.Draw(strip)

    # Monospace font for the cell text
    cell_font = _best_mono_font(size=max(10, cell_h // 10))

    for i in range(n_frames):
        cell_x = i * (cell_w + 10)
        # Per-frame variation: shift text or add motion glyph
        glyph = motion_glyphs[i % len(motion_glyphs)]
        text = glyph + "\n" + rendered
        # Draw the text centered in the cell
        bbox = draw.multiline_textbbox((0, 0), text, font=cell_font, spacing=2)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = cell_x + (cell_w - tw) // 2
        ty = (cell_h - th) // 2
        # Draw text in solid dark color so chroma-key keeps the text
        draw.multiline_text(
            (tx, ty), text,
            fill=(25, 25, 30, 255),
            font=cell_font,
            spacing=2,
            align="center",
        )

    strip.save(out_path)
    return out_path


def _ascii_ident_from_desc(desc: str) -> str:
    """Derive a short 2-4 character identifier for ASCII rendering."""
    desc = (desc or "").strip().upper()
    if not desc:
        return "?"
    # Take first letter of each word, up to 4
    words = [w for w in desc.split() if w.isalpha()]
    if words:
        ident = "".join(w[0] for w in words[:4])
        return ident[:4]
    # Just strip to alnum and take first 4
    return "".join(c for c in desc if c.isalnum())[:4] or "?"


def _motion_glyphs_for(animation: str) -> List[str]:
    """Return a list of motion glyphs to overlay per frame, based on
    the animation name. Gives ASCII strips a pose cue."""
    a = (animation or "").lower()
    if "walk" in a or "run" in a:
        return [">", ">>", ">>>", ">>"]
    if "jump" in a:
        return ["^", "^^", "^^^", "^^"]
    if "punch" in a or "attack" in a:
        return [".", "-", "=>", "=>>"]
    if "kick" in a:
        return [",", ";", "/", "//"]
    if "idle" in a:
        return ["-", "~", "-", "~"]
    if "hit" in a or "hurt" in a or "block" in a:
        return ["!", "X", "!", "."]
    if "sleep" in a or "down" in a:
        return ["z", "zz", "zzz", "z"]
    return [".", "-", ".", "-"]


def _best_mono_font(size: int = 12):
    """Find a monospace font we can actually load."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


# --- Backend 3: fal (stub) -------------------------------------------

def _generate_via_fal(prompt: str, out_path: str, **kwargs) -> str:
    """fal.ai backend stub. Returns a clear error until credits are added
    and the real wrapper is implemented."""
    raise NotImplementedError(
        "fal backend is not wired up. Set FAL_KEY and implement the real "
        "call here, or switch to backend='image_gen' or backend='ascii'."
    )


# --- Public API: generate a single strip -----------------------------

def generate_strip(
    animation: str,
    out_path: str,
    n_frames: int = 4,
    cell_w: int = 96,
    cell_h: int = 96,
    character_desc: str = "",
    style_desc: str = "16-bit pixel art",
    backend: str = "image_gen",
    image_gen_callable: Optional[ImageGenCallable] = None,
    extra_instructions: str = "",
) -> str:
    """Generate one animation strip. Returns path to the saved PNG.

    For image_gen backend, the caller's image_gen_callable is invoked
    with the composed prompt. For ascii backend, rendered entirely
    locally — no external calls.
    """
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    if backend == "ascii":
        return _generate_via_ascii(
            animation=animation,
            n_frames=n_frames,
            cell_w=cell_w,
            cell_h=cell_h,
            character_desc=character_desc,
            out_path=out_path,
        )
    elif backend == "image_gen":
        prompt = build_strip_prompt(
            animation=animation,
            n_frames=n_frames,
            cell_w=cell_w,
            cell_h=cell_h,
            character_desc=character_desc,
            style_desc=style_desc,
            extra_instructions=extra_instructions,
        )
        return _generate_via_image_gen(
            prompt=prompt,
            image_gen_callable=image_gen_callable,
            out_path=out_path,
        )
    elif backend == "fal":
        prompt = build_strip_prompt(
            animation=animation,
            n_frames=n_frames,
            cell_w=cell_w,
            cell_h=cell_h,
            character_desc=character_desc,
            style_desc=style_desc,
            extra_instructions=extra_instructions,
        )
        return _generate_via_fal(prompt=prompt, out_path=out_path)
    else:
        raise ValueError(f"unknown backend: {backend!r}")


# --- Public API: generate from template ------------------------------

def generate_sheet_from_template(
    template_path: str,
    out_dir: str,
    animation_set: str = "min_viable_set",
    backend: str = "image_gen",
    image_gen_callable: Optional[ImageGenCallable] = None,
    character_desc: str = "",
    style_desc: str = "16-bit pixel art",
    cell_w: int = 96,
    cell_h: int = 96,
) -> Dict:
    """Generate one strip per animation state in the named set.

    Returns a dict with per-strip paths and the matching template
    metadata (frame counts, timing data, etc.) so the assembler step
    can stitch them into a final sheet + JSON.
    """
    os.makedirs(out_dir, exist_ok=True)
    with open(template_path, "r") as f:
        template = json.load(f)

    sets = template.get("sets") or template.get("animation_sets") or {}
    anims = None
    for key in (animation_set, "min_viable_set", "standard_set"):
        if key in sets:
            anims = sets[key]
            break
    if anims is None:
        # Fall back to all states defined in the template
        anims = list((template.get("states") or {}).keys())

    states = template.get("states") or {}
    results = {
        "template": template_path,
        "animation_set": animation_set,
        "strips": [],
    }
    for state_name in anims:
        state = states.get(state_name) or {}
        frames = state.get("frames", {}).get("recommended", 4) if isinstance(state.get("frames"), dict) else 4
        safe = "".join(c if c.isalnum() else "_" for c in state_name)
        out_path = os.path.join(out_dir, f"{safe}.png")
        try:
            path = generate_strip(
                animation=state.get("generation_prompt") or state_name,
                out_path=out_path,
                n_frames=int(frames),
                cell_w=cell_w,
                cell_h=cell_h,
                character_desc=character_desc,
                style_desc=style_desc,
                backend=backend,
                image_gen_callable=image_gen_callable,
            )
            results["strips"].append({
                "animation": state_name,
                "path": path,
                "n_frames": int(frames),
                "state_id": state.get("id"),
                "frame_data": state.get("frame_data"),
            })
        except Exception as e:
            results["strips"].append({
                "animation": state_name,
                "path": None,
                "error": str(e),
            })
    return results


# --- CLI -------------------------------------------------------------

def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="Sprite Forge generator")
    sub = parser.add_subparsers(dest="cmd")

    strip = sub.add_parser("strip", help="Generate one animation strip")
    strip.add_argument("--animation", required=True)
    strip.add_argument("--out", required=True)
    strip.add_argument("--backend", default="ascii", choices=["image_gen", "ascii", "fal"])
    strip.add_argument("--frames", type=int, default=4)
    strip.add_argument("--cell-w", type=int, default=96)
    strip.add_argument("--cell-h", type=int, default=96)
    strip.add_argument("--character", default="")

    args = parser.parse_args()
    if args.cmd == "strip":
        path = generate_strip(
            animation=args.animation,
            out_path=args.out,
            n_frames=args.frames,
            cell_w=args.cell_w,
            cell_h=args.cell_h,
            character_desc=args.character,
            backend=args.backend,
        )
        print(f"wrote {path}")
    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
