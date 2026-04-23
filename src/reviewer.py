#!/usr/bin/env python3
"""
Sprite Forge Reviewer — generate an HTML review tool for marking frames good/bad.

Takes an analyzer.json + the original sprite sheet and produces a self-contained
HTML file the user opens in a browser. The reviewer shows every frame in a grid
with quality metrics, lets the user mark GOOD or BAD with one click, pick
pre-populated causes for bad frames, assign animation names, and export a
review.json that regenerator.py consumes.

Usage:
    python3 src/reviewer.py <analyzer.json> <sheet.png> [-o review.html]

The user opens review.html in a browser, reviews frames, clicks "Export Review",
and downloads review.json. That file feeds into regenerator.py.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


def _embed_image_as_data_uri(image_path: str) -> str:
    """Read a PNG and return a data: URI for embedding in HTML."""
    with open(image_path, "rb") as f:
        raw = f.read()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:image/png;base64,{b64}"


def generate_review_html(
    analyzer_json_path: str,
    sheet_path: str,
    out_path: str,
    template_path: Optional[str] = None,
) -> str:
    """Generate a self-contained HTML review tool.

    Returns the path to the written HTML file.
    """
    with open(analyzer_json_path, "r") as f:
        analyzer_data = json.load(f)

    # Load template common_issues if available
    common_issues_by_state = {}
    if template_path and os.path.exists(template_path):
        with open(template_path, "r") as f:
            template = json.load(f)
        for state in template.get("states", []):
            name = state.get("name", "")
            issues = state.get("common_issues", [])
            if issues:
                common_issues_by_state[name] = issues

    # Embed the sheet as a data URI
    sheet_data_uri = _embed_image_as_data_uri(sheet_path)

    # Build the frame data for JS
    frames_js = json.dumps(analyzer_data.get("frames", []))
    row_groups_js = json.dumps(analyzer_data.get("row_groups", []))
    summary_js = json.dumps(analyzer_data.get("summary", {}))
    bg_mode = analyzer_data.get("bg_mode", "auto")
    total_frames = analyzer_data.get("total_frames", 0)
    analyzer_basename = os.path.basename(analyzer_json_path)
    sheet_basename = os.path.basename(sheet_path)
    common_issues_js = json.dumps(common_issues_by_state)

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Sprite Forge — Reviewer</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Courier New', Courier, monospace;
    background: #0a0a0a; color: #d8d8d8;
    padding: 16px;
  }}
  h1 {{ color: #7af; font-size: 20px; margin-bottom: 4px; }}
  .meta {{ color: #666; font-size: 12px; margin-bottom: 12px; }}
  .meta b {{ color: #888; }}

  /* Stats bar */
  .stats {{
    display: flex; gap: 16px; flex-wrap: wrap;
    background: #111; border: 1px solid #222; border-radius: 4px;
    padding: 10px 14px; margin-bottom: 14px; font-size: 13px;
  }}
  .stats .stat {{ white-space: nowrap; }}
  .stats .stat .val {{ color: #7af; font-weight: bold; }}

  /* Toolbar */
  .toolbar {{
    display: flex; gap: 8px; flex-wrap: wrap;
    margin-bottom: 14px; align-items: center;
  }}
  .toolbar button {{
    background: #1a1a2a; color: #ccc; border: 1px solid #333;
    padding: 6px 14px; font-family: inherit; font-size: 13px;
    cursor: pointer; border-radius: 3px;
  }}
  .toolbar button:hover {{ background: #252535; border-color: #555; }}
  .toolbar button.primary {{
    background: #1a3a2a; border-color: #3a6; color: #afa;
    font-weight: bold;
  }}
  .toolbar button.primary:hover {{ background: #254a35; }}
  .toolbar button.danger {{
    background: #3a1a1a; border-color: #a33; color: #faa;
  }}
  .toolbar .spacer {{ flex: 1; }}

  /* Frame grid */
  .grid {{
    display: flex; flex-wrap: wrap; gap: 6px;
  }}
  .frame-card {{
    position: relative;
    border: 2px solid #333; border-radius: 4px;
    background: #151515; cursor: pointer;
    transition: border-color 0.15s, box-shadow 0.15s;
    padding: 0; overflow: hidden;
  }}
  .frame-card:hover {{ border-color: #555; }}
  .frame-card.good {{
    border-color: #3a6;
    box-shadow: 0 0 6px rgba(50, 170, 100, 0.3);
  }}
  .frame-card.rejected {{
    border-color: #a33;
    box-shadow: 0 0 6px rgba(170, 50, 50, 0.3);
  }}
  .frame-card.selected {{
    border-color: #7af;
    box-shadow: 0 0 8px rgba(120, 170, 255, 0.5);
  }}

  .frame-card canvas {{
    display: block;
    image-rendering: pixelated;
  }}
  .frame-info {{
    padding: 3px 5px; font-size: 10px; color: #888;
    border-top: 1px solid #222; background: #111;
    line-height: 1.4;
  }}
  .frame-info .idx {{ color: #7af; }}
  .frame-info .qual {{ padding: 1px 4px; border-radius: 2px; font-size: 9px; }}
  .frame-info .qual.good {{ background: #1a3a2a; color: #7c7; }}
  .frame-info .qual.empty {{ background: #222; color: #555; }}
  .frame-info .qual.sparse {{ background: #2a2a1a; color: #aa7; }}
  .frame-info .qual.blurry {{ background: #2a1a2a; color: #a7a; }}
  .frame-info .qual.noisy {{ background: #3a2a1a; color: #da7; }}

  .frame-status {{
    position: absolute; top: 2px; right: 2px;
    font-size: 14px; font-weight: bold;
    text-shadow: 0 0 4px #000, 0 0 2px #000;
  }}

  /* Cause picker modal */
  .modal-overlay {{
    display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.7); z-index: 100;
    justify-content: center; align-items: center;
  }}
  .modal-overlay.active {{ display: flex; }}
  .modal {{
    background: #151520; border: 1px solid #444; border-radius: 6px;
    padding: 20px; max-width: 500px; width: 90%;
    box-shadow: 0 4px 20px rgba(0,0,0,0.5);
  }}
  .modal h3 {{ color: #faa; margin-bottom: 12px; font-size: 15px; }}
  .modal .cause-list {{
    display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 14px;
  }}
  .modal .cause-btn {{
    background: #1a1a2a; color: #ccc; border: 1px solid #333;
    padding: 5px 12px; font-family: inherit; font-size: 12px;
    cursor: pointer; border-radius: 3px;
  }}
  .modal .cause-btn:hover {{ background: #252535; border-color: #a33; }}
  .modal .cause-btn.selected {{
    background: #3a1a1a; border-color: #a33; color: #faa;
  }}
  .modal textarea {{
    width: 100%; background: #0a0a0a; color: #ccc; border: 1px solid #333;
    padding: 8px; font-family: inherit; font-size: 12px;
    border-radius: 3px; resize: vertical; min-height: 50px;
  }}
  .modal .modal-actions {{
    display: flex; gap: 8px; justify-content: flex-end; margin-top: 12px;
  }}
  .modal .modal-actions button {{
    padding: 6px 16px; font-family: inherit; font-size: 13px;
    cursor: pointer; border-radius: 3px;
  }}
  .modal .btn-cancel {{
    background: #222; color: #888; border: 1px solid #333;
  }}
  .modal .btn-apply {{
    background: #3a1a1a; color: #faa; border: 1px solid #a33;
    font-weight: bold;
  }}

  /* Animation name input */
  .anim-assign {{
    margin-bottom: 14px; padding: 10px 14px;
    background: #111; border: 1px solid #222; border-radius: 4px;
  }}
  .anim-assign label {{ color: #888; font-size: 12px; }}
  .anim-assign input {{
    background: #0a0a0a; color: #ccc; border: 1px solid #333;
    padding: 4px 8px; font-family: inherit; font-size: 12px;
    border-radius: 3px; margin-left: 6px; width: 120px;
  }}

  /* Row sections */
  .row-section {{
    margin-bottom: 16px;
  }}
  .row-header {{
    color: #7af; font-size: 13px; margin-bottom: 6px;
    padding-bottom: 4px; border-bottom: 1px solid #222;
    display: flex; align-items: center; gap: 8px;
  }}
  .row-header input {{
    background: #0a0a0a; color: #ccc; border: 1px solid #333;
    padding: 2px 6px; font-family: inherit; font-size: 12px;
    border-radius: 3px; width: 140px;
  }}

  /* Keyboard shortcuts */
  .shortcuts {{
    position: fixed; bottom: 10px; right: 10px;
    background: #111; border: 1px solid #222; border-radius: 4px;
    padding: 8px 12px; font-size: 11px; color: #666;
  }}
  .shortcuts kbd {{
    background: #222; border: 1px solid #333; border-radius: 2px;
    padding: 1px 4px; font-family: inherit; color: #888;
  }}
</style>
</head>
<body>

<h1>Sprite Forge — Frame Reviewer</h1>
<div class="meta">
  Sheet: <b>{sheet_basename}</b> &nbsp;|&nbsp;
  Analyzer: <b>{analyzer_basename}</b> &nbsp;|&nbsp;
  BG: <b>{bg_mode}</b> &nbsp;|&nbsp;
  Frames: <b>{total_frames}</b>
</div>

<div class="stats" id="stats"></div>

<div class="toolbar">
  <button onclick="markSelected('good')" title="Mark selected as GOOD (G)">✓ Mark Good</button>
  <button onclick="markSelected('rejected')" class="danger" title="Mark selected as BAD (B)">✗ Mark Bad</button>
  <button onclick="clearSelected()" title="Clear status of selected">Clear</button>
  <span class="spacer"></span>
  <button onclick="markAllGood()" title="Mark ALL frames good">All Good</button>
  <button onclick="markAllEmpty()" class="danger" title="Mark all empty/sparse/blurry frames as bad">Auto-reject bad quality</button>
  <span class="spacer"></span>
  <button onclick="exportReview()" class="primary" title="Download review.json">⬇ Export Review</button>
</div>

<div id="row-sections"></div>

<!-- Cause picker modal -->
<div class="modal-overlay" id="causeModal">
  <div class="modal">
    <h3>Why is frame <span id="causeFrameIdx">?</span> bad?</h3>
    <div class="cause-list" id="causeList"></div>
    <label style="color:#888; font-size:12px;">Notes (optional):</label>
    <textarea id="causeNotes" placeholder="Describe the issue..."></textarea>
    <div class="modal-actions">
      <button class="btn-cancel" onclick="closeCauseModal()">Cancel</button>
      <button class="btn-apply" onclick="applyCause()">Apply</button>
    </div>
  </div>
</div>

<div class="shortcuts">
  <kbd>Click</kbd> select &nbsp; <kbd>Shift+Click</kbd> multi &nbsp;
  <kbd>G</kbd> good &nbsp; <kbd>B</kbd> bad &nbsp; <kbd>C</kbd> clear
</div>

<script>
// ── Data injected by reviewer.py ──
const FRAMES = {frames_js};
const ROW_GROUPS = {row_groups_js};
const SUMMARY = {summary_js};
const COMMON_ISSUES = {common_issues_js};
const SHEET_URI = {json.dumps(sheet_data_uri)};

// ── State ──
let sheetImg = null;
let selectedFrames = new Set();
let frameStatuses = {{}};  // index -> {{ status, causes, notes, animation }}
const DEFAULT_CAUSES = [
  "cropped_off", "blurry_low_res", "wrong_animation",
  "duplicate_frame", "extra_noise_artifacts", "background_bleed",
  "inconsistent_size", "wrong_color_palette", "empty_frame",
  "merged_sprites", "missing_frame", "custom"
];

// ── Load sheet ──
const img = new Image();
img.onload = () => {{ sheetImg = img; renderAll(); }};
img.src = SHEET_URI;

// ── Render ──
function renderAll() {{
  renderStats();
  renderGrid();
}}

function renderStats() {{
  const total = FRAMES.length;
  let good = 0, rejected = 0, unmarked = 0;
  for (const f of FRAMES) {{
    const s = frameStatuses[f.index];
    if (!s || !s.status) unmarked++;
    else if (s.status === 'good') good++;
    else if (s.status === 'rejected') rejected++;
  }}
  document.getElementById('stats').innerHTML = `
    <div class="stat">Total: <span class="val">${{total}}</span></div>
    <div class="stat">Good: <span class="val" style="color:#7c7">${{good}}</span></div>
    <div class="stat">Bad: <span class="val" style="color:#faa">${{rejected}}</span></div>
    <div class="stat">Unmarked: <span class="val" style="color:#aa7">${{unmarked}}</span></div>
    <div class="stat">Quality — Good: <span class="val">${{SUMMARY.good||0}}</span>
      Empty: <span class="val">${{SUMMARY.empty||0}}</span>
      Sparse: <span class="val">${{SUMMARY.sparse||0}}</span>
      Blurry: <span class="val">${{SUMMARY.blurry||0}}</span>
      Noisy: <span class="val">${{SUMMARY.noisy||0}}</span></div>
  `;
}}

function renderGrid() {{
  const container = document.getElementById('row-sections');
  container.innerHTML = '';

  if (ROW_GROUPS.length > 0) {{
    ROW_GROUPS.forEach((row, ri) => {{
      const section = document.createElement('div');
      section.className = 'row-section';

      const header = document.createElement('div');
      header.className = 'row-header';
      header.innerHTML = `Row ${{ri}} (${{row.length}} frames)
        <input type="text" placeholder="animation name"
               value="${{getRowAnimName(ri)}}"
               onchange="setRowAnimName(${{ri}}, this.value)"
               onclick="event.stopPropagation()">`;
      section.appendChild(header);

      const grid = document.createElement('div');
      grid.className = 'grid';
      row.forEach(entry => {{
        grid.appendChild(createFrameCard(entry.index));
      }});
      section.appendChild(grid);
      container.appendChild(section);
    }});
  }} else {{
    const section = document.createElement('div');
    section.className = 'row-section';
    const grid = document.createElement('div');
    grid.className = 'grid';
    FRAMES.forEach((f, i) => {{
      grid.appendChild(createFrameCard(i));
    }});
    section.appendChild(grid);
    container.appendChild(section);
  }}
}}

function getRowAnimName(rowIdx) {{
  // Check if any frame in this row has an animation name set
  if (ROW_GROUPS[rowIdx]) {{
    for (const entry of ROW_GROUPS[rowIdx]) {{
      const s = frameStatuses[entry.index];
      if (s && s.animation) return s.animation;
    }}
  }}
  return '';
}}

function setRowAnimName(rowIdx, name) {{
  if (ROW_GROUPS[rowIdx]) {{
    for (const entry of ROW_GROUPS[rowIdx]) {{
      if (!frameStatuses[entry.index]) frameStatuses[entry.index] = {{}};
      frameStatuses[entry.index].animation = name;
    }}
  }}
}}

function createFrameCard(idx) {{
  const f = FRAMES[idx];
  const card = document.createElement('div');
  card.className = 'frame-card';
  card.dataset.index = idx;

  const s = frameStatuses[idx];
  if (s && s.status) card.classList.add(s.status);
  if (selectedFrames.has(idx)) card.classList.add('selected');

  // Canvas for the frame crop
  const canvas = document.createElement('canvas');
  const scale = f.bounds[2] > 96 || f.bounds[3] > 96 ? 0.5 : 1;
  // Display at 2x minimum for visibility
  const displayScale = Math.max(2, Math.floor(96 / Math.max(f.bounds[2], f.bounds[3])));
  canvas.width = f.bounds[2] * displayScale;
  canvas.height = f.bounds[3] * displayScale;
  canvas.style.width = canvas.width + 'px';
  canvas.style.height = canvas.height + 'px';

  if (sheetImg) {{
    const ctx = canvas.getContext('2d');
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(sheetImg,
      f.bounds[0], f.bounds[1], f.bounds[2], f.bounds[3],
      0, 0, canvas.width, canvas.height
    );
  }}

  card.appendChild(canvas);

  // Status badge
  const badge = document.createElement('div');
  badge.className = 'frame-status';
  if (s && s.status === 'good') badge.textContent = '✓';
  else if (s && s.status === 'rejected') badge.textContent = '✗';
  card.appendChild(badge);

  // Info bar
  const info = document.createElement('div');
  info.className = 'frame-info';
  const qualClass = f.quality || 'good';
  let causeText = '';
  if (s && s.causes && s.causes.length) causeText = ' — ' + s.causes[0];
  info.innerHTML = `<span class="idx">#${{idx}}</span>
    <span class="qual ${{qualClass}}">${{f.quality||'?'}}</span>
    ${{f.bounds[2]}}x${{f.bounds[3]}}${{causeText}}`;
  card.appendChild(info);

  // Click handler
  card.addEventListener('click', (e) => {{
    if (e.shiftKey) {{
      toggleSelect(idx);
    }} else {{
      selectedFrames.clear();
      toggleSelect(idx);
    }}
    renderAll();
  }});

  // Double-click to toggle good/bad
  card.addEventListener('dblclick', (e) => {{
    e.preventDefault();
    const cur = frameStatuses[idx];
    if (cur && cur.status === 'good') {{
      openCauseModal(idx);
    }} else if (cur && cur.status === 'rejected') {{
      delete frameStatuses[idx].status;
      delete frameStatuses[idx].causes;
      delete frameStatuses[idx].notes;
    }} else {{
      frameStatuses[idx] = Object.assign(frameStatuses[idx] || {{}}, {{ status: 'good' }});
    }}
    renderAll();
  }});

  return card;
}}

function toggleSelect(idx) {{
  if (selectedFrames.has(idx)) selectedFrames.delete(idx);
  else selectedFrames.add(idx);
}}

// ── Marking ──
function markSelected(status) {{
  if (status === 'rejected') {{
    // Open cause picker for the first selected frame
    const first = [...selectedFrames][0];
    if (first !== undefined) {{
      openCauseModal(first, () => {{
        // Apply to rest
        for (const idx of selectedFrames) {{
          if (!frameStatuses[idx]) frameStatuses[idx] = {{}};
          if (!frameStatuses[idx].status) {{
            frameStatuses[idx].status = 'rejected';
            frameStatuses[idx].causes = frameStatuses[first]?.causes || [];
            frameStatuses[idx].notes = frameStatuses[first]?.notes || '';
          }}
        }}
        renderAll();
      }});
      return;
    }}
  }}
  for (const idx of selectedFrames) {{
    if (!frameStatuses[idx]) frameStatuses[idx] = {{}};
    frameStatuses[idx].status = status;
    if (status === 'good') {{
      delete frameStatuses[idx].causes;
      delete frameStatuses[idx].notes;
    }}
  }}
  renderAll();
}}

function clearSelected() {{
  for (const idx of selectedFrames) {{
    delete frameStatuses[idx];
  }}
  renderAll();
}}

function markAllGood() {{
  for (const f of FRAMES) {{
    if (!frameStatuses[f.index]) frameStatuses[f.index] = {{}};
    frameStatuses[f.index].status = 'good';
    delete frameStatuses[f.index].causes;
    delete frameStatuses[f.index].notes;
  }}
  renderAll();
}}

function markAllEmpty() {{
  for (const f of FRAMES) {{
    if (['empty','sparse','blurry','noisy'].includes(f.quality)) {{
      if (!frameStatuses[f.index]) frameStatuses[f.index] = {{}};
      frameStatuses[f.index].status = 'rejected';
      frameStatuses[f.index].causes = [f.quality === 'empty' ? 'empty_frame' :
        f.quality === 'blurry' ? 'blurry_low_res' :
        f.quality === 'noisy' ? 'extra_noise_artifacts' : 'cropped_off'];
      frameStatuses[f.index].notes = 'auto-rejected: ' + f.quality;
    }}
  }}
  renderAll();
}}

// ── Cause modal ──
let causeTarget = null;
let causeCallback = null;
let selectedCauses = [];

function openCauseModal(idx, callback) {{
  causeTarget = idx;
  causeCallback = callback || null;
  selectedCauses = [];
  document.getElementById('causeFrameIdx').textContent = '#' + idx;
  document.getElementById('causeNotes').value = '';

  // Check if this frame has template-specific issues
  const frame = FRAMES[idx];
  let causes = DEFAULT_CAUSES;
  // Could customize per-row based on animation assignment
  if (frameStatuses[idx] && frameStatuses[idx].animation) {{
    const anim = frameStatuses[idx].animation;
    if (COMMON_ISSUES[anim]) {{
      causes = [...COMMON_ISSUES[anim], ...DEFAULT_CAUSES];
    }}
  }}

  const list = document.getElementById('causeList');
  list.innerHTML = '';
  causes.forEach(c => {{
    const btn = document.createElement('button');
    btn.className = 'cause-btn';
    btn.textContent = c.replace(/_/g, ' ');
    btn.onclick = () => {{
      btn.classList.toggle('selected');
      if (selectedCauses.includes(c)) {{
        selectedCauses = selectedCauses.filter(x => x !== c);
      }} else {{
        selectedCauses.push(c);
      }}
    }};
    list.appendChild(btn);
  }});

  document.getElementById('causeModal').classList.add('active');
}}

function closeCauseModal() {{
  document.getElementById('causeModal').classList.remove('active');
  causeTarget = null;
  causeCallback = null;
}}

function applyCause() {{
  if (causeTarget === null) return;
  const notes = document.getElementById('causeNotes').value.trim();
  if (!frameStatuses[causeTarget]) frameStatuses[causeTarget] = {{}};
  frameStatuses[causeTarget].status = 'rejected';
  frameStatuses[causeTarget].causes = selectedCauses.length ? selectedCauses : ['custom'];
  if (notes) frameStatuses[causeTarget].notes = notes;

  if (causeCallback) {{
    causeCallback();
  }}
  closeCauseModal();
  renderAll();
}}

// ── Export ──
function exportReview() {{
  const review = {{
    sheet_path: {json.dumps(sheet_basename)},
    analyzer_input: {json.dumps(analyzer_basename)},
    timestamp: new Date().toISOString(),
    frames: FRAMES.map(f => {{
      const s = frameStatuses[f.index] || {{}};
      return {{
        index: f.index,
        bounds: f.bounds,
        status: s.status || 'unmarked',
        quality: f.quality || 'unknown',
        animation: s.animation || '',
        causes: s.causes || [],
        notes: s.notes || ''
      }};
    }})
  }};

  const blob = new Blob([JSON.stringify(review, null, 2)], {{ type: 'application/json' }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'review.json';
  a.click();
  URL.revokeObjectURL(url);
}}

// ── Keyboard shortcuts ──
document.addEventListener('keydown', (e) => {{
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  if (e.key === 'g' || e.key === 'G') markSelected('good');
  else if (e.key === 'b' || e.key === 'B') markSelected('rejected');
  else if (e.key === 'c' || e.key === 'C') clearSelected();
  renderAll();
}});
</script>
</body>
</html>'''

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


# ── CLI ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Sprite Forge Reviewer — generate HTML review tool"
    )
    parser.add_argument("analyzer_json", help="Path to analyzer JSON output")
    parser.add_argument("sheet", help="Path to sprite sheet PNG")
    parser.add_argument("-o", "--output", default=None,
                        help="Output HTML path (default: <sheet>_review.html)")
    parser.add_argument("--template", default=None,
                        help="Fighter template JSON for common_issues hints")

    args = parser.parse_args()

    if not os.path.exists(args.analyzer_json):
        print(f"Error: {args.analyzer_json} not found")
        sys.exit(1)
    if not os.path.exists(args.sheet):
        print(f"Error: {args.sheet} not found")
        sys.exit(1)

    out = args.output or str(Path(args.sheet).stem + "_review.html")
    path = generate_review_html(
        analyzer_json_path=args.analyzer_json,
        sheet_path=args.sheet,
        out_path=out,
        template_path=args.template,
    )
    print(f"Review tool: {path}")
    print(f"Open in browser, mark frames, click 'Export Review' to download review.json")


if __name__ == "__main__":
    main()
