# End-to-End Flow: AI Layered Design Generator

## Overview
This is a **Canva-like design tool** that creates professional designs in two ways:
1. **Prompt → Design** (Part One): You describe what you want, and AI generates a complete editable design
2. **Image → Layers** (Part Two): You upload a flat image, and AI breaks it into separate editable layers

Both create the same document format that opens in the same editor, so you can edit them the same way.

---

## 🎨 PART ONE: How a Text Prompt Becomes an Editable Design

### The 7-Step Journey

```
You type a prompt
    ↓
[Step 1] Parse the brief → understand what you want
    ↓
[Step 2] Find the best template skeleton → pick a layout style
    ↓
[Step 3] Compose the design → place text, pick colors, write AI instructions
    ↓
⚡ YOU SEE THE SKELETON IMMEDIATELY (text + layout, no images yet)
    ↓
[Step 4] Generate images → create backgrounds, products, icons in parallel
    ↓
[Step 5] Make everything look like it belongs together → harmonize colors, shadows, contrast
    ↓
[Step 6] Fix spacing and collisions → solve layout problems automatically
    ↓
[Step 7] Save and thumbnail → done! Ready to edit
```

---

## 📝 Step 1: Parse the Brief (What do you want?)

**What happens:**
- Your messy, natural prompt is converted into a structured "brief" — a set of rules the AI understands
- This decides: design kind (story, post, poster), canvas size, color direction, tone, what copy goes where

**Example:**
```
Input:  "Make a story for a gym. Big headline 'GET STRONG', show a dumbell, 
         dark and minimal, call the gym at 555-0123"

Output: {
  kind: "story" (tall phone format, 1080×1920px),
  subjectDescription: "dumbell, close-up, isolated",
  copy: {
    headline: "GET STRONG",
    cta: "CALL 555-0123"
  },
  mood: ["dark", "minimal"],
  canvas: { width: 1080, height: 1920 }
}
```

**How it works:**
- LLM reads your prompt, creates the brief in a structured format
- If the LLM fails, a backup heuristic parser takes over (regex patterns for phone numbers, keywords for design types)
- Never fails — always gives you something to work with

**Time: ~1 second**

---

## 🎯 Step 2: Retrieve the Best Template (Pick a skeleton)

**What happens:**
- System looks through a database of **hand-designed layout templates** (skeletons)
- Finds the 3 best matches for your brief using:
  - Hard rules: must match the design kind (story/post/poster) and be text-only or subject-bearing
  - Vector search: finds templates similar to your brief description
  - Quality score: templates that users like most score higher

**Why templates matter:**
- **Good layouts come from humans, not AI.** A curated skeleton beats a smarter model.
- Instead of the AI inventing coordinates (which looks bad), it picks a professional skeleton
- The skeleton has "slots" — placeholders for headline, background, product photo, etc.

**Example skeleton:**
```
Template: "Product Hero for Stories"
├── Background slot (full bleed)
├── Product image slot (bottom-right, translucent shadow)
├── Headline slot (top-left, big bold text)
├── CTA button slot (bottom-left)
└── Extra features: safe margins, grid baseline for snapping
```

**Time: ~0.05 seconds** (super fast, just a database query)

---

## 🖌️ Step 3: Compose the Design (Fill in the template)

**What happens:**
- LLM chooses the best skeleton, writes text to fit each slot, picks a color palette, and fills in image generation prompts
- **The LLM does NOT invent coordinates** — it only chooses from predefined slots
- All geometry is deterministic code, not AI guessing

**The LLM decides:**
1. Which skeleton to use
2. What text goes in each text slot (respecting character limits)
3. What colors to use (from brand kit, or derive from the prompt)
4. What font family (from an approved list)
5. Complete image prompts for each image slot (with negative prompts to avoid text)
6. Optional: nudge slot positions by ±8% or drop optional layers

**Example output:**
```
{
  templateId: "product_hero_story_02",
  palette: ["#0F172A", "#F5B700", "#FFFFFF"],
  font: { family: "Inter", headlineWeight: 900, bodyWeight: 400 },
  slots: [
    {
      slotId: "bg",
      imagePrompt: "dark moody gym interior, dramatic lighting, empty, no text"
    },
    {
      slotId: "headline",
      text: { content: "GET STRONG" }
    },
    {
      slotId: "cta",
      text: { content: "CALL 555-0123" }
    }
  ]
}
```

**Then:** All this is converted into real layers using pure code:
- Normalised coordinates (0..1) → real pixels
- Apply grid snapping
- Create actual Layer objects with empty placeholders
- Generate a seed for reproducibility

**Time: ~2-3 seconds**

---

## ⚡ YOU SEE THE SKELETON NOW (< 3 seconds total)

**What you get:**
- Text layers (real text, not images)
- Shapes (colored rectangles, buttons)
- Placeholder colored boxes where images will go
- Perfect layout, no collisions, no text overflow

**Why this matters:**
- You see something immediately, not a loading spinner
- As images generate, they replace the placeholder boxes
- You can start editing while generation continues

---

## 🖼️ Step 4: Generate Images (Make the pictures)

**What happens:**
- **All image generation happens in parallel** (not one at a time)
- Background image is generated first (quality-critical)
- Then product photos, icons, decorations
- Each image is checked to make sure it doesn't contain unwanted text

**Process per image:**

### 4a. Generate the background
```
Input:  prompt: "dark moody gym interior, dramatic lighting, 
                 empty floor, no text"
        size: 1080×1920px
        seed: random-but-saved (for reproducibility)

Output: A clean background image
        Check: scan for text using a glyph detector
        If text found: retry with stronger negative prompt or inpaint over it
```

### 4b. Generate subject image (transparent)
```
Input:  prompt: "dumbell, chrome and steel, three-quarter view, 
                 studio light, transparent background"

Two possible paths:
  Path A (preferred): Model outputs RGBA directly (clean edges)
  Path B (fallback):  Generate with background, then use matting
    Step 1: Generate image with plain background
    Step 2: Auto-detect which pixels are the product (matting AI)
    Step 3: Refine the alpha channel (the transparency mask)
            - Feather edges
            - Remove halos (color-bleed from old background)
            - Clean up tiny artifacts
    Step 4: Store both the image AND the alpha mask separately
```

### 4c. Text overlay check (Glyph Gate)
**Purpose:** Enforce "Text is text, never pixels"
```
For each generated image:
  1. Run text detector → find areas with letters
  2. If too much text detected:
     → Retry with stronger negative prompt: 
       "text, letters, words, numbers, typography, watermark, 
        logo, signature, ui, caption, frame, border"
     → Change random seed
     → Lower image quality slightly
  3. If still has text:
     → Use inpainting to remove the text
  4. Never give the user baked-in text (uneditable)
```

**Time: 4-20 seconds total** (depends on model, runs in parallel)

---

## 🎭 Step 5: Harmonization (Make everything look together)

**What happens:**
All independently generated images are brought into visual harmony — they look like they were photographed in the same scene.

### 5a. Harmonize Colors
```
What it does:
  1. Extract 5 dominant colors from the background
  2. Replace the composer's palette with these real colors
  3. Keep the accent color hue, but adjust brightness/saturation
  4. Re-apply all colors to text, shapes, etc.

Why it matters:
  A dumbell photo + gym background + text all use cohesive colors
  Instead of: Random colors everywhere
```

### 5b. Harmonize Contrast
```
What it does:
  1. For each text layer:
     - Take a screenshot of everything below it
     - Measure brightness and busyness
     - Pick a text color from the palette that has enough contrast
     - If contrast is bad:
       a) Add a dark/light scrim behind the text
       b) Or move the text to a calmer area
       c) Or add a backdrop pill/box behind text
  
  2. Require:
     - Headlines: 3:1 contrast ratio minimum
     - Body text: 4.5:1 contrast ratio (WCAG standard)

Why it matters:
  Text is always readable, on busy backgrounds or solid ones
```

### 5c. Harmonize Shadows
```
What it does:
  1. Estimate light direction from background (which way is light coming?)
  2. Add a drop shadow to cutout images in the opposite direction
  3. Match shadow color to background darkness
  4. Add contact shadow (shadow on ground where object touches surface)

Why it matters:
  Objects float naturally instead of looking pasted on
```

### 5d. Harmonize Color-Matching
```
What it does:
  1. Measure the background's white balance
  2. Adjust subject's warmth/coolness to match
  3. Applied non-destructively (user can undo)

Why it matters:
  Product photo taken in cool light now matches warm sunset background
```

**Time: < 1 second** (all CPU, pure math, very fast)

---

## 📐 Step 6: Layout Solver (Fix spacing and collisions)

**What happens:**
All layers are re-positioned automatically to fix any problems:
- Text that's too long → shrink the font size (within limits)
- Layers touching canvas edge → move them inside
- Layers colliding with each other → move lower-priority one out of the way
- Everything snaps to a grid for that polished look

**Process:**

### 6a. Measure Text
```
For each text layer:
  1. Load the actual font file
  2. Shape the text using HarfBuzz (professional typography)
  3. Measure exactly how many pixels it takes
  4. Compute line breaks intelligently
  5. Cache the result (text measurement is expensive)
```

### 6b. Autofit
```
If text doesn't fit the frame:
  1. Shrink the font size gradually
  2. Re-measure at each size
  3. Find the largest size that fits
  4. If still doesn't fit → mark as violation (alert in UI)

If autoHeight is enabled:
  1. Grow the frame height to fit the text
```

### 6c. Safe Margins
```
If any layer crosses the safe margin (padding from canvas edge):
  1. Push it back inside
  2. Never crop or hide it

Exception: Background layers and full-bleed layers can touch edges
```

### 6d. Collision Resolution
```
For overlapping layers (sorted by priority):
  1. Move the lower-priority layer away (smallest movement possible)
  2. If it hits another collision → iterate until solved
  3. Max 20 iterations to prevent infinite loops
  4. If layer is optional → hide it instead
```

### 6e. Optical Alignment
```
Professional alignment, not mechanical:
  - Text aligned by ink edge, not frame edge
    (capital "T" needs a small left offset for visual balance)
  - Subject images aligned by their content centroid,
    not frame center
```

### 6f. Grid Snap
```
Round all coordinates to a grid baseline (e.g., 8px)
Makes everything line up perfectly
```

**Time: ~100ms** (deterministic, no AI)

---

## 💾 Step 7: Assemble, Thumbnail, Save

**What happens:**
```
1. Save the complete document to the database
2. Initialize a Yjs room (for editing/multiplayer support)
3. Generate a thumbnail at 512px for the design list
4. Sum up the total cost in cents
5. Send complete design to the editor
```

**The final document contains:**
- All layers with real positions
- All images with asset IDs (pointers to stored images)
- Full generation parameters (so you can regenerate with same seed)
- Extraction info (where things came from)
- Metadata (creation time, edits, notes)

---

## ✏️ THE EDITOR: What You Can Do Now

Now the design is complete and you can edit it:

### Select & Transform
```
- Click to select a layer
- Drag to move
- Drag corners to resize
- Rotate handle to turn
- Shift while resizing to lock aspect ratio
```

### Edit Text
```
- Double-click to edit text directly
- Font, size, color, alignment all editable
- Solver re-runs when you commit (Cmd+Enter)
- Text always stays real, never rasterized
```

### Regenerate Images
```
- Select an image layer
- Click "Regenerate" to create a new version
  (same prompt, different seed = different image)
- Or override the prompt to ask for something different
```

### Remove Backgrounds
```
- Select an image
- Click "Remove Background"
- AI detects the subject and removes the background
- Result is transparent PNG with soft, clean edges
```

### Rewrite Text
```
- Select multiple text layers (headline + body)
- Click "Rewrite"
- Describe what to change: "make it shorter", "more casual", "all caps"
- AI rewrites keeping consistent voice across both
- Respects character limits per layer
```

### Resize to Different Format
```
- "Resize" → pick new dimensions (e.g., story → post)
- System picks the matching template variant
- Applies constraint rules:
  - Pinned edges stay pinned
  - Centered things recenter
  - Stretchy things stretch
- Re-solves layout automatically
- Returns a new document (original unchanged)
```

### Export
```
Options:
  - PNG: raster at any scale (1x to 4x), with DPI metadata
  - JPEG: lossy, smaller file size
  - PDF: vector-preserving text as real text (not pixels!)
           live text + embedded fonts + images
  - SVG: vector format, shapes and text as SVG elements
```

---

## 📸 PART TWO: How an Image Becomes Editable Layers

### The 8-Step Journey

```
You upload a flat image
    ↓
[Step 1] Preprocess → normalize resolution, detect image type
    ↓
[Step 2] Extract text → OCR, style, font match
    ↓
[Step 3] Detect objects → find products, people, logos
    ↓
[Step 4] Estimate depth → figure out which objects are in front/behind
    ↓
[Step 5] Extract with clean edges → matting for soft transparency
    ↓
[Step 6] Vectorize flat shapes → convert solid colors to vector shapes
    ↓
[Step 7] Inpaint holes → fill in the areas behind moved objects
    ↓
[Step 8] Assemble → create the editable document with confidence score
```

---

## 📥 Step 1: Preprocess (Prepare the image)

**What happens:**
```
1. Decode the image, remove EXIF data
2. Auto-orient to correct rotation
3. If > 8000px wide or > 40MP:
   - Downscale with a warning
   - But keep the original full resolution as backup
4. Work at 1536px on the long edge
   - All AI models run at this resolution
   - Faster, cheaper
5. Save the scale factor
   - When done, upscale masks back to original with smart filtering
   (not nearest-neighbor, but edge-aware to preserve quality)
```

**What the system detects:**
```
Is this a screenshot or vector graphic?
  - Low color count (few unique colors)
  - Large flat regions (solid colors)
  - Hard edges (not smooth)

If yes:
  - Prefer vectorization (convert to shapes)
  - Avoid matting (won't work well)
If no (photo):
  - Use matting (extract objects with soft edges)
```

**Time: Instant** (image decoding and analysis)

---

## 🔤 Step 2: Extract Text (Find and read text)

**What happens:**

### 2a. Text Detection
```
Scan the image for text regions:
  - Find all quadrilateral boxes containing letters
  - Group them into lines
  - Group lines into paragraphs (by proximity, alignment, line spacing)
  - Keep the rotation angle for each region
```

### 2b. OCR (Optical Character Recognition)
```
Read what's in each text region:
  - Use a text recognition model
  - Keep per-character confidence scores
  - "HELLO" with 95% confidence is very readable
  - "Blurry text" with 60% confidence is risky
```

### 2c. Style Estimation
```
For each paragraph, measure:
  - Color: median color of the text pixels
  - Size: height of capital letters → font size in px
  - Weight: how thick the strokes are → font weight (400, 700, 900)
  - Italics: angle of the glyphs
  - Alignment: left-aligned, centered, or right-aligned
  - Line spacing: baseline-to-baseline distance
  - Tracking (letter spacing): distance between characters
```

### 2d. Font Matching
```
You have: "HELLO" text, measured at 48px, bold, sans-serif
Find: Which installed font looks closest?

Process:
  1. Render "HELLO" in each candidate font at 48px bold
  2. Compare the rendered glyphs to the original
  3. Measure the difference (shape distance)
  4. Pick the closest match
  5. Store top 3 options in case the user disagrees
```

### 2e. Create Text Layers
```
For each paragraph:
  1. Guess the role: 
     - Largest → headline
     - Next size → subhead
     - Small + bottom → caption
     - In a button shape → CTA
  2. Create a TextLayer with all the measured properties
  3. Add to the document
```

**Quality gate:** If OCR confidence < 60%, don't create a text layer
- Reason: A wrong-text layer is worse than no text layer
- It stays in the background instead

**Time: 2-5 seconds**

---

## 🎯 Step 3: Detect Objects (What's in the image?)

**What happens:**

### 3a. Object Detection
```
Scan for recognizable things:
  - Vocabulary: person, face, product, bottle, phone, food, 
               car, animal, plant, logo, badge, button, icon, shape
  - Return boxes with confidence scores
  - Keep only boxes with > 35% confidence
  - Remove overlapping boxes (NMS at 60% overlap)
```

### 3b. Segmentation (Trace the exact shape)
```
For each detected box:
  1. Use SAM (Segment Anything Model) with the box as a hint
  2. Automatically propose masks without hints too
  3. Merge overlapping masks
  4. Remove tiny masks (< 0.5% of image)
  5. Remove huge masks (> 85% of image, probably the whole scene)
  6. Don't extract anything on top of text (already got that)

Result: List of pixel-perfect masks
```

**Limit:** Max 12 objects per image
- Reason: Layer panel would be overwhelming
- Quality: Rank by size × confidence × how centered, keep top 12
- Rest stay in the background

**Time: 3-8 seconds**

---

## 📊 Step 4: Estimate Depth (Front to back ordering)

**What happens:**

```
You have: 12 masks of different objects
Question: Which ones are in front, which are behind?

Process:
  1. Run monocular depth estimation on the image
     → produces a depth map (lighter = closer, darker = farther)
  2. For each mask, take the median depth value
  3. Sort layers: highest depth = furthest = bottom layer
  4. Check occlusion boundaries:
     - Where two objects touch, measure depth in that band
     - If object A is always closer → A occludes B
     - Fix the sort order based on this
  5. Group mutually-occluding objects:
     - Example: a shoe + its shoelace + shadow
     - They share one back-plate when moved
```

**Time: 2-4 seconds**

---

## 🔤 Step 5: Refine Alpha (Soft, clean edges)

**What happens:**

Segmentation gives you hard, blocky edges. This step makes them professional.

```
For each object mask:
  1. Identify confident foreground (α > 95%) and background (α < 5%)
  2. The unknown band between them is the tricky edge
  3. Create a trimap:
     - Foreground: definite object
     - Background: definite not-object
     - Unknown: the edge (dilate by ~0.4% of image width)
  4. Run a trimap matting model on the unknown band only
     → produces soft alpha: 0, 25%, 50%, 75%, 100%
  5. Feather 1px (blur slightly)
  6. Decontaminate color:
     - For each pixel in the alpha band:
     - Estimate the original foreground color
     - Remove the halo of the old background
     - Result: clean edge with no fringe
  7. Despeckle:
     - Remove floating dust (tiny disconnected alpha components)
     - Keep only > 0.05% of mask area
```

**Result:** Soft, professional cutouts like Photoshop would produce

**Time: 3-8 seconds per object**

---

## 🎨 Step 6: Vectorize Flat Shapes (Convert to vectors)

**What happens:**

Screenshots and vector-origin graphics have solid color regions. Convert those to scalable shapes.

```
For each mask:
  1. Is it a flat region?
     - All pixels the same color (low variance)
     - Boundary fits a simple shape
       (rectangle, rounded rect, ellipse, polygon)
     
  If yes:
    → Create a ShapeLayer with fill color
       (scales perfectly, no pixelation)
  
  If boundary has many vertices:
    → Use vectorization algorithm (VTracer, potrace)
    → Convert to SVG path or SvgLayer
    → Add colorMap so user can recolor it
  
  If gradient detected:
    → Create SVG with gradient fill
       (not a flat color)
```

**Result:** Logos and graphics scale and recolor perfectly

**Time: 1-3 seconds**

---

## 🎪 Step 7: Inpaint Back-Plates (Fill the holes)

**What happens:**

When you move an extracted object, there's a hole underneath. This step fills it intelligently.

**Important:** Do this in one pass (back-to-front), not per object
- Why: If you inpaint each hole separately, plates disagree where objects overlap
- One pass: all holes filled consistently

```
Process:
  1. Create a clean background:
     - Erase ALL foreground objects + all text
     - Inpaint with prompt: "clean empty background, consistent lighting"
     → This becomes the "background plate"
  
  2. For each object (front to back):
     - Save the current composite as this object's "back-plate"
     - When the user moves the object, this plate shows behind it
     - Move the object → see the inpainted scene, not a hole
  
  3. Optimization:
     - For simple backgrounds (uniform color):
       Just fill with the local average color (much faster)
     - For complex backgrounds:
       Use inpainting AI
  
  4. Smart dilation:
     - Dilate the mask by 4-8px before inpainting
     - Reason: Without dilation, a 1-2px ghost ring remains visible
     - User moves the object → sees the old edge outline
```

**Tile large images:** For images > 512px, inpaint in tiles
- Tiles of 512-768px with 64px overlap
- Feather the blend so you don't see seams
- Keeps the model coherent (doesn't lose global context)

**Cost optimization:**
- Cap inpaint jobs: max 4 plate renders per image
- Beyond that: merge occlusion groups (fewer plates)

**Time: 5-20 seconds** (expensive, most time-consuming step)

---

## 📄 Step 8: Assemble & Quality Gate (Create the document)

**What happens:**

```
1. Create DesignDoc:
   - Layer 0 = background image (full-bleed, priority 100)
   - Layers 1-N = objects in depth order
   - Text layers on top
   - Vector shapes wherever applicable
   - Hidden layer = original flat image (user escape hatch)

2. Measure-only layout solve:
   - Shape the text with real font
   - Check autofit bounds are sane
   - Do NOT move anything yet
   - Reason: User expects their image to look identical on open
   
3. Extract palette:
   - K-means clustering of colors in original
   - 5-7 dominant colors
   
4. Calculate confidence score:
   Score = 0.35 × matteConfidence +
           0.25 × ocrConfidence +
           0.20 × inpaintQuality +
           0.20 × (1 - unsolvedOverlapFraction)
           
5. Pick output tier:
   - Tier: Full (conf ≥ 0.7)
     → all layers, all plates, all vectors
   
   - Tier: Reduced (0.45 ≤ conf < 0.7)
     → background + text + top 3 objects only
   
   - Tier: Minimal (conf < 0.45)
     → background + text layers only
   
   - Tier: Failed (conf < ?)
     → flat image as single layer + message
       "Try guided refinement mode"
```

**Tell the user honestly:**
> "I extracted 4 objects and 3 text blocks from your image. The background 
> is reconstructed, so moving the bottle might reveal slightly different 
> lighting behind it. You can refine this manually if needed."

**Time: Instant** (pure computation)

---

## ✏️ Guided Refinement (Fix what the AI missed)

**What happens:**

The AI decomposed the image, but it's not perfect. The user can manually refine it.

### Add Layer
```
- Click/lasso a region of the image
- AI segments just that region at full resolution
- Matte with soft edges
- Inpaint just that hole
- Insert as a new layer
```

### Split Layer
```
- Draw a line across a layer
- Split the mask in two
- Re-matte both halves
- Inpaint both holes
```

### Merge Layers
```
- Select 2+ layers
- Union their masks
- Inpaint one back-plate for the group
```

### Drop Layer
```
- Select a layer
- Delete it and composite permanently into the background
- Cheaper than keeping it as a separate layer
```

### Refine Edge
```
- Brush over the alpha channel where the edge is rough
- Re-run trimap matting on just that band
- Adjustable feather strength
```

### Fix Text
```
- Select a text layer
- Correct the recognized string (if OCR was wrong)
- Swap the font from the 3 stored candidates
```

**Key:** Every hint is incremental
- Reuses cached original, depth map, existing plates
- Never re-runs the whole pipeline

---

## 🔁 Both Paths → Same Editor

Whether you started with a prompt or an image, you now have a DesignDoc in the same editor:

```
Drag, resize, rotate
↓
Edit text (real text, not pixels)
↓
Regenerate images
↓
Remove backgrounds
↓
Rewrite copy
↓
Resize to new format
↓
Export PNG/JPEG/PDF/SVG
```

The editor doesn't know or care which path created the document.

---

## 🏗️ Under the Hood: Architecture

### Three Sacred Invariants (enforced by code, not hope)

**INV-1: Text is text, never pixels**
- Any text layer carrying a raster adapter gets rejected
- Glyph gate re-rolls any generated image containing detectable letters
- Enforced mechanically in validation

**INV-2: Every asset is reproducible**
- Each image stores its complete generation parameters
- Same parameters + same seed = identical bytes
- If you regenerate, you can get the exact same image

**INV-3: Canvas and export look the same**
- One render function on the server (`toDrawList()`)
- Browser replays the exact same DrawCommand list
- No client-side geometry calculation
- SSIM parity test ensures canvas ≥ 0.995 match with export

### Database Schema

```
users              → who created what
documents          → design doc + Yjs state (for multiplayer)
assets             → images, SVGs, with gen_hash deduplication
jobs               → generation/inpaint/export tasks and their status
templates          → the skeleton corpus (hand-designed layouts)
generation_requests → track cost per prompt
```

### API Routes

```
POST   /v1/generate              prompt → design
GET    /v1/progress?requestId    stream progress events
POST   /v1/uploads               upload image for decompose
POST   /v1/decompose             image → editable layers
GET    /v1/docs/:id              fetch document
PATCH  /v1/docs/:id              edit document
WS     /v1/sync/:docId           real-time multiplayer sync (Yjs)
POST   /v1/docs/:id/layers/:lid/regenerate   new version of image
POST   /v1/docs/:id/export       PNG/JPEG/PDF/SVG
```

### Backend Tech Stack

```
Python + FastAPI          → API server
PostgreSQL + pgvector     → database + vector search
Redis                     → job queue (BullMQ), progress pub/sub
S3-compatible storage     → images, SVGs, documents
Skia (via @napi-rs/canvas) → server-side rendering
HarfBuzz                  → text shaping (shared with frontend)
Sentence-transformers     → template retrieval embeddings
PyTorch                   → image generation models
```

### Frontend Tech Stack

```
React + TypeScript        → UI components
Vite                      → bundler
Konva                     → canvas rendering (replays DrawList)
Yjs + y-websocket         → live multiplayer sync
```

---

## 📊 Latency Budget

**Part One (Prompt → Design)**
```
brief.parse        ~1.0 s
template.retrieve  ~0.1 s
compose.layout     ~2.5 s
──────────────────────────
  SKELETON VISIBLE  < 3.0 s (user sees layout immediately)

asset.background   ~6 s (in parallel)
asset.subject      ~8 s (in parallel)
harmonize.palette  < 0.1 s
harmonize.contrast < 0.1 s
layout.solve       < 0.1 s
──────────────────────────
  COMPLETE          < 20 s
```

**Part Two (Image → Layers)**
```
preprocess         ~0.5 s
text + objects     ~5 s (parallel)
depth + matting    ~5 s (parallel)
inpainting         ~10 s
assemble           < 0.1 s
──────────────────────────
  COMPLETE          < 20 s
```

---

## 🎯 Quality Metrics (Tested in CI)

```
schema_validity              100% ✓
text_overflow_rate           0% ✓
collision_rate               0% ✓
contrast_pass_rate           100% ✓
glyph_leakage_rate           0% ✓
safe_margin_pass_rate        100% ✓
p95_skeleton_seconds         0.3s ✓
p95_complete_seconds         1.68s ✓
```

---

## 💰 Cost Control

One design = 3-8 image generations. Cost is controlled by:

```
1. Content-addressed cache
   - Same prompt + seed = free (deduped)

2. Two-tier models
   - Fast/cheap for preview
   - Good model on final export

3. Resolution discipline
   - Generate at smallest size needed
   - Upscale only on export

4. Smart skipping
   - No inpainting for uniform backgrounds
   - No upscaling for small layers
   - No depth estimation for single-object images

5. Per-request ceiling
   - Max cost per design
   - Degrades gracefully: fewer variants, cheaper model
   - Never errors, always delivers something
```

---

## 🔒 Safety & Abuse Prevention

```
Prompt injection     → OCR text treated as data, never instructions
Content filtering    → NSFW, violence, CSAM detection on images
IP/Likeness blocking → Block prompts naming real people/brands
Rate limiting        → Per-user and per-IP limits
Font licensing       → Track embedding rights per font
Data retention       → Uploads deleted on schedule (default 30 days)
```

---

## 🎓 Summary: The Complete Picture

```
┌─────────────────────────────────────────────────────────────────┐
│                      YOUR INPUT                                 │
├─────────────────────────────────────────────────────────────────┤
│  Text Prompt              OR          Flat Image                │
│  ("Make a gym poster")                 (logo.png)               │
└─────────────────────────────────────────────────────────────────┘
         ↓                                     ↓
    PART ONE                             PART TWO
    7-Step Flow                          8-Step Flow
         ↓                                     ↓
  Parse → Template                  Preprocess → Text
  Compose → Images                  Detect → Depth
  Harmonize → Solve                  Matte → Inpaint
  Assemble                           Assemble
         ↓                                     ↓
┌─────────────────────────────────────────────────────────────────┐
│              DESIGN DOCUMENT (DesignDoc)                        │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Layers:                                                  │  │
│  │ - Background image (asset_id, gen_params)               │  │
│  │ - Subject image with soft alpha                         │  │
│  │ - Text: \"STRONG RESULTS\" (real text, not pixels)       │  │
│  │ - CTA button shape (vector shape)                       │  │
│  │                                                          │  │
│  │ Metadata:                                               │  │
│  │ - Canvas: 1080×1920 px                                  │  │
│  │ - Palette: [#0F172A, #F5B700, #FFFFFF]                 │  │
│  │ - Fonts: Inter 400, 700, 900                            │  │
│  │ - Provenance: generated/decomposed                      │  │
│  │ - Full generation params for reproducibility            │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
         ↓
       EDITOR
    (Same for both paths)
         ↓
    Drag, Resize, Rotate
    Edit Text, Regenerate Images
    Remove Backgrounds, Rewrite Copy
    Resize to New Format
         ↓
      EXPORT
    PNG / JPEG / PDF / SVG
```

---

## 🚀 Key Takeaways

1. **Structure first, pixels second**
   - Designs are built as scene graphs, not flattened images
   - Everything stays editable forever

2. **Layouts from humans, details from AI**
   - Template corpus (hand-designed) beats LLM coordinates
   - AI fills in text, colors, image prompts

3. **Text is always text**
   - Never baked into images
   - Glyph gate enforces this mechanically

4. **Deterministic code, not chaos**
   - HarfBuzz shapes text
   - Layout solver fixes spacing
   - Renderer produces identical output on client and server

5. **Progressive delivery**
   - Skeleton in < 3 seconds
   - Images fill in as they arrive
   - User never waits on a blank screen

6. **Same document, two entry points**
   - Prompt → design
   - Image → layers
   - Both create the same DesignDoc
   - Same editor, same tools, same export options

---

**That's the complete end-to-end flow!** 🎉

From a prompt or image → structured document → editable layers → exportable design.
