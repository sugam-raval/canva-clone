# Plan: more creative, less repetitive AI layouts

This plan is for the **Design new template** tab (and `make lido-create AI=1`). It explains,
in simple words, what is wrong today, how we will fix it, and which AI model does what.

Nothing here is built yet. Review it first, then we start.

---

## 1. The problems (seen with the yoga prompt)

| # | Problem | Example |
|---|---|---|
| 1 | **Photo count is fixed** | The brief asks for 3 yoga poses, but the design shows only 1–2 photos |
| 2 | **Users don't know feature names** | Nobody writes "hollow text" or "brush_band frame" in a prompt, so the AI rarely uses these features |
| 3 | **Layouts look the same** | Many designs share the same structure: headline on top, photo, list, button |
| 4 | **The brief's "don'ts" are ignored** | "No prices" but a price tag still appears |

**Why it happens:** today **one AI call does everything at once**. It reads the brief,
decides the content, picks the style, places every element and writes the text. When an
AI is asked to do too much in one go, it plays safe and repeats what it has seen before.

---

## 2. The solution: two AI steps, like a real design agency

In an agency, the **art director** first decides *what* the design is. Then the
**designer** builds it. We do the same.

```
Your prompt
    │
    ▼
┌──────────────────────────────┐
│ STEP 1: ART DIRECTOR (AI)    │   Reads the prompt and writes a short PLAN:
│                              │   - how many photos, and what each one shows
│                              │   - the mood (calm, bold, luxury, playful…)
│                              │   - which frames, shapes, drawings, effects fit
│                              │   - which layout to use (from the catalogue)
│                              │   - what NOT to add (no price, no badge…)
└──────────────┬───────────────┘
               │ plan
               ▼
┌──────────────────────────────┐
│ STEP 2: DESIGNER (AI)        │   Places every element on the canvas,
│                              │   following the plan exactly.
└──────────────┬───────────────┘
               │ layout
               ▼
┌──────────────────────────────┐
│ CHECKS (code, not AI)        │   Same checks as today, plus:
│                              │   - photo count = what the plan said
│                              │   - planned frames/features are used
│                              │   - nothing the brief said "don't" appears
└──────────────────────────────┘
```

### What the art director writes for the yoga prompt (example)

```
Text:       headline "BREATHE. STRETCH. TRANSFORM."
            subline  "Make Yoga a Part of Your Everyday Life"
            button   "Start Your Yoga Journey Today"
Don't add:  price, offer badge, promotional claims
Photos:     3 →  1. a woman in Tree Pose outdoors at sunrise
                 2. a man in Warrior Pose on a yoga mat in a bright studio
                 3. a person in Lotus Pose meditating among green plants
Mood:       calm, organic, airy, premium wellness
Features:   soft blob and brush photo frames · a soft sunrise gradient
            · a hand-drawn squiggle as a divider · a gentle lift on the headline
            · thin lines · no sharp geometric shapes
Layout:     "staggered trio": 3 photos stepping diagonally, headline above
```

This fixes problems 1, 2 and 4:

- **Photo count comes from the brief.** "3 poses" gives 3 photos, "our new product" gives 1,
  "before and after" gives 2. The maximum goes up from **2 to 4**.
- **The user never needs feature names.** The art director turns *feelings* into
  *features* with a **mood → feature map** (below).
- **Don'ts are respected.** If the brief says "no prices", the plan says no price tag, and
  the checks make sure of it.

### The mood → feature map (the art director's cheat sheet)

| When the prompt feels… | The art director picks… |
|---|---|
| calm, wellness, yoga, spa, organic | soft blob, egg and brush frames · soft gradients · squiggles · lift effect · lots of space |
| sale, offer, discount, "limited time" | burst-style badges · dashed coupon box · hollow word · chevrons · bold colours |
| tech, launch, modern, premium | radial spotlight · hexagons · thin lines with arrow ends · shadow · dark background |
| kids, fun, party, playful | scalloped and gem frames · zigzag · sparkles · bright shapes · rotated tiles |
| luxury, elegant, jewellery | thin lines · gem frame · serif fonts · hollow word · lots of empty space |
| food, fresh, café, bakery | brush and torn-paper frames · hand-drawn circle around the price · underline |
| corporate, finance, law | clean lines · hexagon or rounded-card frames · simple geometry · no doodles |
| events, festival, music | gradient background · slanted bands · big type · sparkles |

---

## 3. Why layouts repeat, and the fix (in simple words)

### 3a. "Layout catalogue (30–40)": a **menu of layouts**

Today the AI invents a layout from scratch every time. It has no list to choose from,
so it falls back on its favourite one.

**The fix:** we write a **menu** of 30–40 different layout ideas, like a restaurant menu.
Each item is a short description of one way to arrange a post. For example:

| Layout name | What it looks like |
|---|---|
| Staggered trio | 3 photos stepping diagonally across the post |
| Magazine cover | One big photo filling the post, headline across the top |
| Diagonal split | The post cut in two by a slanted line: photo one side, text the other |
| Z-pattern | Text top-left → photo top-right → photo bottom-left → button bottom-right |
| Filmstrip | A row of 3–4 small photos like film frames |
| Big letter | One huge letter with a photo inside it, text beside it |
| Floating card | A full photo background with a text card floating on it |
| Centre stage | The photo in the middle, small badges and text around it |
| Polaroid stack | 2–3 tilted photos with white borders, like printed photos on a table |
| 2×2 grid | 4 photos in a grid, headline across the middle |

The art director **picks the menu item that fits the brief best**. For 3 yoga poses that
might be "staggered trio", "filmstrip" or "polaroid stack". Different briefs get
different items, so designs stop looking the same.

### 3b. "Memory": a **notebook of past designs**

Today the AI forgets everything after each design, so tomorrow it may make the same
layout again.

**The fix:** after every design we write one line in a **notebook**, e.g.
*"staggered trio, blob frames, sunrise gradient"*. Before the next design, the art
director reads the last 10 lines and is told **"pick something different from these"**.

### 3c. "Rotating example pool": **show different examples each time**

Today the AI always sees the **same 3 example designs** before it starts. People copy
what they are shown, and so does the AI.

**The fix:** we keep 10+ example designs and **show only 2 random ones** each time.
So it's copying a different style each time, not always the same 3.

### 3d. "Layout skeletons": an **empty floor plan with boxes**

Today the AI decides every x, y, width and height itself. That's hard for it, so it
keeps to simple shapes.

**The fix:** for each menu layout, **our code draws the empty floor plan**: "photo box
here, photo box there, headline box here", with slightly random sizes each time. The AI
then only fills the boxes (which frame, which text, which decoration). It's like
furnishing a house that's already built instead of building it from bricks.

- More reliable: fewer failed checks.
- Every design is different, because the boxes are shuffled every time.

**3a + 3b give most of the benefit. 3c + 3d are extra polish.**

---

## 4. Which AI model does which job

Your `.env` has two models:

| Name in `.env` | Model | What it's like |
|---|---|---|
| `LLM_MODEL` | `gpt-6-astra` (reasoning, effort `low`) | **Smart but slow** (~30–60 s). Good at careful thinking: geometry, positions, fixing mistakes |
| `LLM_MODEL_FAST` | `gpt-4o-mini` | **Fast but simpler** (~3–8 s). Good at reading and summarising text |

### The plan

| Step | Job | Model | Why |
|---|---|---|---|
| **1. Art director** | Read the brief → count photos, find text, mood, don'ts, pick features and layout | **`LLM_MODEL_FAST`** | It's a **reading and understanding** job with a short answer. A fast model does this well. Saves 30+ seconds |
| **2. Designer** | Place every element with exact pixel positions | **`LLM_MODEL`** (reasoning) | It's a **geometry** job: things must fit, not overlap, and be balanced. The fast model makes many more mistakes here, which means more repairs and more total time |
| **Repairs** (only if checks fail) | Fix the listed problems | **`LLM_MODEL`** (reasoning) | Same job as the designer, so the same smart model |

**Expected time per design:** about **5 s (plan) + 40 s (layout) = ~45–50 s**. Today it's
about 40 s, so only a few seconds more.

### You can change it later without code

We'll add two settings to `backend/.env`:

```
LIDO_PLAN_MODEL=gpt-4o-mini      # step 1 (default: LLM_MODEL_FAST)
LIDO_LAYOUT_MODEL=               # step 2 + repairs (empty = LLM_MODEL)
```

If the plans are too weak, set `LIDO_PLAN_MODEL` to the reasoning model. If you want
everything faster and accept lower quality, set `LIDO_LAYOUT_MODEL=gpt-4o-mini`.

---

## 5. One decision for you: the logo

Some prompts say "no logo" (like the yoga one). Today every template **must** have one
logo slot, because the design guide and the pipeline expect it: a template is reused by
many businesses, and most want their logo on it.

| Option | Effect |
|---|---|
| **A. Always keep a small logo slot** *(suggested)* | Every template stays reusable; "no logo" in a prompt is ignored for the slot |
| **B. Allow no logo when the prompt says so** | Follows the prompt exactly, but that template can't show a business's logo later |

---

## 6. Build order

| Order | What | Fixes |
|---|---|---|
| 1 | Art director step + mood → feature map + "don'ts" + model settings | Problems 2 and 4 |
| 2 | Up to 4 photos + multi-photo layouts | Problem 1 (the yoga case) |
| 3 | Layout menu (30–40) + memory notebook | Problem 3 (repetition) |
| 4 | Rotating example pool + layout skeletons | Extra polish for problem 3 |

After each step we test with the same prompts (yoga, PC launch, vegetable, coffee, kids
camp) and compare the results before moving on.

---

## 7. How we'll know it worked

| Test prompt | We expect |
|---|---|
| Yoga (3 poses, calm, no prices) | **3 photos** in soft organic frames · calm gradient · no price or badge |
| PC launch (product, features, price) | 1 big product photo · tech look (spotlight, hexagons, lines) · price shown |
| Vegetable sale | Fresh look (brush or torn frame, hand-drawn circle on the price) · offer badge |
| Kids camp (3 activities) | Playful frames and doodles · 3 activity items with bullets |
| The same prompt 5 times | 5 clearly different layouts |
