# Skeleton System — Technical Design

**Status:** Prototype in `sandbox/skeleton_editor.html`  
**Branch:** `skeleton-pipeline` (experimental, may merge into `elephant` when stable)  
**Philosophy:** No neural networks. Pure geometry + image manipulation. Fast, consistent, fully transparent.

---

## The Core Idea

Instead of asking an AI to generate every frame from scratch, we ask it once:

> "Give me a side-view reference image of my character in a neutral standing pose."

Then we slice that single image into articulated body parts and warp them into any pose by computing joint angles and applying rotational transforms.

**Analogy:** It's a digital action figure or articulated paper doll. You don't redraw the doll for every pose — you rotate the limbs at the joints.

---

## Why Two Skeleton Types?

| Type | Body Proportions | Use Case |
|------|-----------------|----------|
| **Female** | Smaller shoulders (0.42x width), wider hips, shorter torso ratio, graceful limb curvature | Female characters, elegant fighters |
| **Male** | Broader shoulders (0.48x width), narrower hips, longer torso, straighter limbs | Male characters, athletic fighters |
| **Animal** | Quadruped spine, digitigrade legs, tail anchor | Beast characters, furries, monsters |
| **Custom** | User-defined proportions | Anything else |

The proportions affect:
1. Where preset joints are placed when auto-loading
2. Which reference poses are suggested
3. Joint rotation limits (e.g., knee bend max angle)

---

## Terminology

- **Joint:** A point on the skeleton with an (x,y) position. Has a label, an ID, and a type.
- **Bone:** A connection between two joints. Determines which image region rotates together.
- **Sleeve (slicing region):** The rectangular image strip around a bone — what's actually rotated.
- **Pose:** A snapshot of all joint positions at one moment in time.
- **Animation:** A sequence of poses with timing data.

---

## The Pipeline

```
Step 1: REFERENCE IMAGE
    Upload or generate one side-view character image.
    Must show full body, head to toe, unobstructed.

Step 2: PLACE JOINTS
    Click on the image to place joints, or load a preset.
    Presets align to anatomical landmarks.

Step 3: DEFINE SLICES
    At each bone midpoint, the system cuts perpendicular to the bone.
    Each slice becomes an independent image region (a "patch").

Step 4: POSE
    Drag joints to bend limbs. The patches rotate around their joints.
    The system re-composites all patches into a new image.

Step 5: ANIMATE
    Save poses as keyframes. Interpolate joint positions between them.
    Export a sprite sheet (posed frames stitched together).
```

---

## Slicing Algorithm (The Key Trick)

This is what makes it work without ML. Given a bone between joints A and B:

1. Compute the bone direction vector: `v = B - A`
2. Compute a perpendicular vector: `perp = normalize(-v.y, v.x)`
3. Define the sleeve width (e.g., 40 pixels around the bone centerline)
4. Extract the image region as a quadrilateral bound by:
   - `A + perp * width`  (top-left around A)
   - `A - perp * width`  (bottom-left around A)
   - `B + perp * width`  (top-right around B)
   - `B - perp * width`  (bottom-right around B)
5. Store this patch. When joint A or B moves, rotate the patch around that joint.
6. Composite all rotated patches back onto a canvas, drawing in layer order:
   - Back limbs first (lower Z)
   - Torso
   - Head
   - Front limbs last (higher Z)

This is essentially 2D rigid-body articulation. It only breaks down when:
- A limb bends too far and the sleeve width causes self-intersection
- The reference pose is far from the target pose (large joint angle change)

Both are solvable with joint rotation limits and reference-pose expansion (generate 2-3 base poses instead of 1).

---

## Advantages Over AI-Per-Frame

| | AI Per-Frame | Skeleton Rigger |
|---|---|---|
| **Cost** | $0.05-$0.20 per frame | $0.05-$0.20 total (one reference) |
| **Speed** | 5-30s per frame (API latency) | <100ms per frame (local JS) |
| **Consistency** | Limbs/eyes/clothing drift | Pixel-perfect consistency |
| **Control** | "Prompt and pray" | Drag joints, exact angles |
| **Failures** | Extra limbs, wrong poses, grid bleed | Only breaks at extreme joint angles |
| **Iteration** | Regen rejected frames individually | Drag joint, instant preview |
| **Best for** | Unique poses, idle variations | Walk cycles, combos, chains |

---

## Limitations (Honest)

1. **Needs a clean side-view reference.** 3/4 view, front view, or cluttered backgrounds don't work.
2. **Extreme poses distort.** A punch at 160 degrees from reference creates obvious stretching. Solution: generate 2-3 reference poses (neutral, mid-action, peak) and blend.
3. **Occlusions are hard.** When a raised arm covers the face, the skeleton system shows both. Solution: Z-layer ordering + optional manual mask painting.
4. **Clothing with flowing elements (capes, hair, skirts)** doesn't articulate naturally. They need secondary animation (physics) not yet implemented.
5. **Facial expressions don't change.** The head is one rigid patch.

---

## How It Integrates Into Sprite Forge Wizard

The current wizard:
```
P0: Welcome → P1: Reference → P2: Idle+Walk → P3: Punch+Kick → P4: Jump+Special → P5: Hit → P6: Final
```

With the skeleton mode, the flow becomes:
```
P0: Welcome (choose generation mode: AI vs Skeleton)
P1: Reference (same as now)
P1b: Place Joints (new — only if skeleton mode)
    ↓
P2-P5: POSE ANIMATIONS (drag joints for each frame instead of AI gen)
    ↓
P6: Final Sheet + Export
```

The UI for P2-P5 changes:
- Instead of "Generate" button → you get a skeletal overlay on the reference image
- Drag joints to the right position for frame 1, click "Save Frame"
- Drag to frame 2 position, click "Save Frame"
- Instant flipbook preview between frames
- Adjust FPS, loop, on-hit timing

---

## Roadmap for This Feature

### v0.1 (now — prototype)
- Single static image preview
- Drag joints, see them move
- Export joint positions as JSON
- Test poses: idle, walk

### v0.2 (working demo)
- Full slicing: extract patches, rotate, composite
- Z-layer ordering (back limbs → torso → front limbs)
- Joint angle constraints (knees don't bend backward)
- Save/load pose library

### v0.3 (integration)
- Merge into `elephant` wizard flow
- Settings tab toggle: "AI Prompt" vs "Skeleton Rig"
- Per-animation drag-and-pose interface replaces the 2x2 grid
- Hermes JSON export with frame data

### v0.4 (polish)
- Multi-reference blending (2-3 base poses)
- Secondary animation: capes, hair, tails
- Hitbox marking per frame
- MUGEN .air export

---

## Open Questions

1. **Should we add a hybrid mode?** AI generates 3-4 reference poses (neutral, action, hurt, special), then skeleton rig interpolates between them. Best of both worlds?
2. **How many joints are enough?** Current human preset = 13 joints. Is that sufficient for fluid animation, or do we need fingers (18+ joints)?
3. **Reference image requirements:** Side-view only for fighters. But platformers need 4-directional. Do we maintain separate reference images per direction, or ask the user to rotate the whole character?

---

## Files

- `sandbox/skeleton_editor.html` — standalone prototype
- `app/ui.html` — settings toggle wiring (Generation Mode buttons)
- `templates/fighter.json` — could eventually contain per-style skeleton presets
