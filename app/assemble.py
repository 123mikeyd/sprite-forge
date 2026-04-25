#!/usr/bin/env python3
"""Assemble sprite sheet from generated grid images in output/."""
import os, sys, json
import numpy as np
from PIL import Image

APP_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(APP_DIR, "output")

TARGET = (96, 96)
GAP = 4

def chroma_key(img, bg='magenta'):
    """Remove background, crop tight, scale to fit TARGET."""
    arr = np.array(img.convert("RGBA"))
    h, w = arr.shape[:2]

    def _is_bg(r, g, b):
        if bg == 'green':
            return r < 80 and g > 160 and b < 80
        if bg == 'blue':
            return r < 80 and g < 80 and b > 160
        return r > 200 and g < 50 and b > 200

    mask = np.zeros((h, w), dtype=bool)
    for y in range(h):
        for x in range(w):
            r, g, b = int(arr[y,x,0]), int(arr[y,x,1]), int(arr[y,x,2])
            if not _is_bg(r, g, b):
                mask[y, x] = True
    if not np.any(mask):
        return Image.new("RGBA", TARGET, (0,0,0,0))
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    rmin, rmax = np.where(rows)[0][[0,-1]]
    cmin, cmax = np.where(cols)[0][[0,-1]]
    pad = 8
    crop = img.crop((max(0,cmin-pad), max(0,rmin-pad), min(w,cmax+pad+1), min(h,rmax+pad+1))).convert("RGBA")
    ca = np.array(crop)
    for y in range(ca.shape[0]):
        for x in range(ca.shape[1]):
            if _is_bg(ca[y,x,0], ca[y,x,1], ca[y,x,2]):
                ca[y,x,3] = 0
    clean = Image.fromarray(ca)
    cw, ch = clean.size
    if cw == 0 or ch == 0:
        return Image.new("RGBA", TARGET, (0,0,0,0))
    scale = min(TARGET[0]/cw, TARGET[1]/ch, 1.0)
    nw, nh = max(1,int(cw*scale)), max(1,int(ch*scale))
    scaled = clean.resize((nw,nh), Image.NEAREST)
    result = Image.new("RGBA", TARGET, (0,0,0,0))
    result.paste(scaled, ((TARGET[0]-nw)//2, (TARGET[1]-nh)//2), scaled)
    return result

def split_grid(path, cols=2, rows=2):
    img = Image.open(path).convert("RGBA")
    w, h = img.size
    cw, ch = w//cols, h//rows
    return [img.crop((c*cw, r*ch, (c+1)*cw, (r+1)*ch)) for r in range(rows) for c in range(cols)]

def assemble(animations, out_dir=OUTPUT_DIR):
    anims = list(animations.keys())
    max_f = max(len(v) for v in animations.values())
    sheet_w = max_f * (TARGET[0]+GAP) + GAP
    sheet_h = len(anims) * (TARGET[1]+GAP) + GAP
    sheet = Image.new("RGBA", (sheet_w, sheet_h), (0,0,0,0))

    fps_map = {"idle":6,"walk":10,"punch":15,"kick":15,"jump":12,"jump_kick":12,"fireball":10,"hurt":12,"knockdown":8,"getup":8}
    loop_map = {"idle":True,"walk":True}

    result_anims = {}
    for ri, name in enumerate(anims):
        y = GAP + ri*(TARGET[1]+GAP)
        rects = []
        for ci, frame in enumerate(animations[name]):
            x = GAP + ci*(TARGET[0]+GAP)
            sheet.paste(frame, (x,y), frame)
            rects.append([x,y,TARGET[0],TARGET[1]])
        result_anims[name] = {"frames":rects, "fps":fps_map.get(name,10), "loop":loop_map.get(name,False)}

    sheet_path = os.path.join(out_dir, "sprite_sheet.png")
    sheet.save(sheet_path)
    json_data = {"version":1, "sheet":"sprite_sheet.png", "size":[sheet_w,sheet_h], "bg_mode":"transparent", "animations":result_anims}
    json_path = os.path.join(out_dir, "sprite.json")
    with open(json_path,"w") as f: json.dump(json_data, f, indent=2)
    return sheet_path, json_path, json_data

if __name__ == "__main__":
    # Expected args: grid1.png anim1,anim2,anim3,anim4 grid2.png anim5,anim6,...
    if len(sys.argv) < 3:
        print("Usage: python3 assemble.py grid1.png idle,walk,walk,walk [grid2.png punch,punch,kick,kick ...]")
        sys.exit(1)

    animations = {}
    i = 1
    while i < len(sys.argv):
        grid_path = sys.argv[i]
        anim_names = sys.argv[i+1].split(",")
        cells = split_grid(grid_path)
        for j, name in enumerate(anim_names):
            if j < len(cells):
                processed = chroma_key(cells[j])
                if name not in animations:
                    animations[name] = []
                animations[name].append(processed)
        i += 2

    sheet_path, json_path, json_data = assemble(animations)
    print(f"Sheet: {sheet_path}")
    print(f"JSON: {json_path}")
    for name, anim in json_data["animations"].items():
        print(f"  {name}: {len(anim['frames'])} frames, {anim['fps']}fps")
