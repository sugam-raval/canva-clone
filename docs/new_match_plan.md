# New plan: picking the best template for a request

Status: **implemented** (2026-09-24). Code: `backend/app/lido_corpus/details.py`,
`match_index.py`, `matcher.py`, `store.py`, wired in through `retrieval.py`. Commands:
`make lido-sync`, `python scripts/lido_match.py show "..."`, `python scripts/lido_match.py test`. Test run: 28 of 28
test requests picked right (27 of 28 without the small AI call).

Differences from the plan below:
- **Storage is Postgres, not a file.** Templates and their embeddings live in the
  `lido_templates` table (pgvector `vector(384)`), mirrored from the JSON files at API
  startup, every `LIDO_TEMPLATE_SYNC_SECONDS`, or with `make lido-sync`. Topic similarity
  is computed by pgvector. The JSON files stay the source you edit.
- A detail the AI call adds only counts if it quotes the exact words from the request. In
  the first run it claimed an "offer" for "Apply today", which sent requests to the wrong
  templates.
- Slot notes are **not** read for details (step A2, point 3). Notes describe neighbouring
  slots ("paired with the phone number") and marked the wrong slots; the role and the
  sample text are enough.
- The `sentence-transformers` package is now installed in `backend/.venv` (§3).
- template_10091's name, tags and description now say "interior design"; before, they
  only said "sale", and interior design requests went to the restaurant template.

This plan explains, in simple steps, how the app will choose the best template from
`lidojs_templates/` when a user types a request.

---

## 1. The idea in one paragraph

Every template can be used for any request. But the user's details must not get lost.
So the app works in this order:

1. **First, find templates that can hold every detail the user gave.** If the user gave a
   phone number, a website and a discount, we look for templates with a phone slot, a
   website slot and an offer slot. If one or more templates have all of them, we pick
   from those only, even when their topic is not the closest.
2. **If no template holds every detail, pick the best overall match.** This uses a
   topic score (how close the template's theme is) and a details score (how many of the
   user's details it can hold).

---

## 2. What we decided

| Decision | Why |
|---|---|
| All templates in `lidojs_templates/` can be picked | You said all of them are ready. The old "must have a reference note" rule is removed. |
| Templates that hold **every** user detail come first | Losing a phone number or an offer is worse than a weaker theme. |
| We do not ask the AI for the canvas size | Not needed for matching. All templates are square today. |
| We always pick a template | Every template is usable. We never refuse. |
| Topic is matched with **local embeddings** | We use the sentence-transformer model already set in `backend/.env` (`SENTENCE_TRANSFORMER_MODEL=sentence-transformers/all-MiniLM-L6-v2`). It runs on this machine: free, no internet call, very fast. |
| Details are matched with simple rules | Phone numbers, emails, websites and "% off" are easy to spot with patterns. |

---

## 3. What is an embedding? (simple version)

An embedding turns a piece of text into a list of numbers (384 numbers for our model).
Texts with similar meaning get similar numbers.

- "Diwali sweets sale" and "festival mithai discount" get **close** numbers.
- "Diwali sweets sale" and "we are hiring a data analyst" get **far apart** numbers.

To compare two texts, we compare their numbers. The result is a similarity from
0 (unrelated) to 1 (same meaning).

**One important limit.** The model in `.env` (`all-MiniLM-L6-v2`) understands English
well, but not Hindi, Marathi or Gujarati. So we never embed a Hindi request directly.
One small AI call first writes a short **English topic line** for the request (step B2),
and we embed that line. Template cards are written in English for the same reason.

**Setup needed once.** The model files are already downloaded on this machine, but the
Python package is not installed in `backend/.venv` yet. One command fixes it:

```bash
cd backend
uv pip install --extra-index-url https://download.pytorch.org/whl/cpu -e ".[embed]"
```

The app already has the code that loads this model (`SentenceTransformerEmbedder`). Today,
because the package is missing, it silently falls back to a fake "hash" embedder that has
no meaning.

---

## 4. The full flow

There are two parts. Part A runs **once**, when templates are added or changed.
Part B runs **for every request**.

```
PART A — build the template index (once)

  each template file
        │
        ├─ 1. Read its text layers, photos and metadata
        ├─ 2. Find which details it has a slot for
        │      (phone, email, website, address, offer, price, date)
        ├─ 3. Write a short English "template card" describing it
        ├─ 4. Turn the card into an embedding (local model)
        └─ 5. Save everything in one index file


PART B — pick a template (every request)

  user request
        │
        ├─ 1. Find which details the user gave
        ├─ 2. Write a short English topic line (one small AI call)
        ├─ 3. Turn the topic line into an embedding (local model)
        ├─ 4. Score every template: topic score and details score
        │
        ├─ 5. Is there any template that holds EVERY detail the user gave?
        │        YES → pick from those only, by topic score
        │        NO  → pick the best total score from all templates
        │
        └─ 6. Return the top 3 with their scores, so we can see why
```

---

## 5. Part A in detail: building the template index

### Step A1. Read the template

We read every text layer, every photo frame, and the metadata (name, tags, description,
slot notes).

### Step A2. Find which details the template has a slot for

A **detail** is one of these seven things:

| Detail | Example |
|---|---|
| phone | `+123-456-7890`, `98765 43210` |
| email | `hello@site.com` |
| website | `www.site.com`, `site.in` |
| address | a street, area or city line |
| offer | `50% off`, `sale`, `discount`, `promo`, `free`, `flat` |
| price | `₹499`, `$20`, `Rs 999` |
| date / time | `25 Oct`, `2026`, `10 AM` |

For each text layer we check:

1. **Its role.** The roles were fixed in this session, so a website is now marked
   `website` and an email `email`, even when the export left the type empty.
2. **Its sample text**, with simple patterns like the examples above.
3. **Its notes**, for words like "offer", "phone" or "contact".

We also record, for the card only, whether the template has a **button** (like "Book
Now"), a **list** (and how many items), and how many **photos**.

Result for the templates in the folder today:

| Template | What it is | Detail slots | Also has |
|---|---|---|---|
| template_10091 | Half-off sale ad (interior design) | offer, website | button, 2 photos |
| template_1635 | Counseling services | phone, website | button, person cutout |
| template_1789 | Job openings | email | button, list of 4 jobs |
| template_1825 | Corporate event services | none | list of 3 features, 3 photos |
| template_227 | Restaurant promo | offer, website | 1 food cutout |
| template_831 | Hair salon services | website | button, list of 4 services, 2 photos |

### Step A3. Write the template card

The card is a few plain English sentences, built from the metadata and the real sample
text. Example for `template_831`:

> Hair salon services post. Big title: HAIR SALON. Lists services: Haircut, Hair Mask,
> Hair Washing, Colouring Hair. Has a Book Now button and a website. Beauty, personal
> care, salon, elegant, brown and cream.

### Step A4. Turn the card into an embedding

The local model turns each card into 384 numbers. This takes a few milliseconds per
template.

### Step A5. Save the index

Everything goes into the Postgres table `lido_templates`. For each template:

- a fingerprint of the template file, so we know when it changed;
- the card text;
- the detail slots found;
- the embedding.

A new command, `make lido-sync`, builds it. The server also rebuilds it by itself for
any template whose file changed, so adding a template needs no extra step.

---

## 6. Part B in detail: picking a template

### Step B1. Find which details the user gave

The same patterns from step A2 run on the user's request. If the request contains
`98765 43210`, the user gave a phone number.

### Step B2. Write an English topic line

One small, cheap AI call (the fast model) reads the request, in any language, and
returns:

- one short English line about the topic;
- a double-check of the details from B1, for example an offer written in Hindi
  ("30% की छूट") that the English patterns missed.

It does **not** decide canvas size or anything else.

- Request: "गणेश चतुर्थी की शुभकामनाएं, परिवार की ओर से"
- Topic line: "Ganesh Chaturthi festival greeting from a family, devotional"

If the AI call fails, we use the request text as it is and the B1 details only.

### Step B3. Embed the topic line

The local model turns the topic line into 384 numbers.

### Step B4. Score every template

**Topic score (0 to 1).** How close the topic line is to the template card. We stretch it
so unrelated templates land near 0 and very close ones near 1.

**Details score (0 to 1).**

```
details score = (user details the template can hold) ÷ (user details given)
```

If the user gave no details, the details score is 1 for every template.

**Empty contact slots.** If the user gives no website, the template keeps its sample text
"www.yourwebsite.com", which looks unfinished. So we count the template's contact slots
the user did not fill. We use this count as a small minus, 0.05 each, below.

### Step B5. Pick the winner (the priority rule)

**Step 1: the "holds everything" group.** Put every template whose details score is 1
into one group. These templates can hold every detail the user gave.

- **If the group has templates:** pick from the group only. Rank them by:

  ```
  rank = topic score − 0.05 × empty contact slots
  ```

- **If the group is empty:** no template can hold everything. Rank **all** templates by:

  ```
  total = 0.6 × topic score + 0.4 × details score − 0.05 × empty contact slots
  ```

The highest wins. If the user gave no details, every template is in the group, so the
pick is simply the closest topic.

If the user picked a template by id, or asked for a random one, we skip all of this,
the same as today.

### Step B6. Show why

The response includes the top 3 templates with their topic score, details score, which
path was used ("holds everything" or "best match"), and which user details have no slot.
The Lido.js (template) tab shows them.

---

## 7. Full examples, end to end

*The topic scores below are realistic estimates. The real ones will come from the
embeddings.*

### Example 1: no template holds everything, so the best match wins

**Request:**

> Diwali sale at Sharma Sweets! Flat 30% off on all mithai. Call 98765 43210 or visit
> www.sharmasweets.in

**B1. Details given:** offer, phone, website (3 details).

**B2. Topic line:** "Diwali festival sale at an Indian sweets shop, discount on mithai"

**B4. Scores:**

| Template | Topic | Holds | Details score | Empty contact slots |
|---|---|---|---|---|
| template_10091 (sale ad) | 0.60 | offer, website | 2 ÷ 3 = 0.67 | 0 |
| template_227 (restaurant) | 0.55 | offer, website | 0.67 | 0 |
| template_1635 (counseling) | 0.10 | phone, website | 0.67 | 0 |
| template_831 (salon) | 0.10 | website | 0.33 | 0 |
| template_1825 (corporate) | 0.15 | nothing | 0 | 0 |
| template_1789 (hiring) | 0.10 | nothing | 0 | 1 (email) |

**B5. Priority rule:**

- Holds-everything group: **empty**. No template has offer + phone + website together.
- So we rank all templates by total:

| Rank | Template | Calculation | Total |
|---|---|---|---|
| 1 | **template_10091** | 0.6 × 0.60 + 0.4 × 0.67 | **0.63** |
| 2 | template_227 | 0.6 × 0.55 + 0.4 × 0.67 | 0.60 |
| 3 | template_1635 | 0.6 × 0.10 + 0.4 × 0.67 | 0.33 |
| 4 | template_831 | 0.6 × 0.10 + 0.4 × 0.33 | 0.19 |
| 5 | template_1825 | 0.6 × 0.15 + 0.4 × 0 | 0.09 |
| 6 | template_1789 | 0.6 × 0.10 + 0.4 × 0 − 0.05 | 0.01 |

**Result:** template_10091. The response says "phone has no slot" so the user knows.

### Example 2: one template holds everything, so it wins over a closer topic

**Request:**

> Beginner yoga classes every morning. Call 98220 12345 or visit www.yogapune.in

**B1. Details given:** phone, website (2 details).

**B2. Topic line:** "Morning yoga classes for beginners, wellness and fitness"

**B4. Scores:**

| Template | Topic | Holds | Details score |
|---|---|---|---|
| template_831 (salon services) | 0.45 | website | 0.50 |
| template_1635 (counseling) | 0.40 | phone, website | **1.00** |
| template_10091 (sale ad) | 0.15 | website | 0.50 |
| others | ≤ 0.20 | website or nothing | ≤ 0.50 |

**B5. Priority rule:**

- Holds-everything group: **template_1635 only**. It is the only template with both a
  phone slot and a website slot.
- So template_1635 wins, even though template_831's topic is a little closer.

**Result:** template_1635. The phone number and website both appear on the design.

### Example 3: no details, so the closest topic wins

**Request:**

> Grand opening of our new hair and beauty salon

**B1. Details given:** none. Every template is in the holds-everything group.

| Template | Topic | Empty contact slots | Rank |
|---|---|---|---|
| **template_831 (salon)** | 0.80 | 1 (website) | **0.75** |
| template_1635 (counseling) | 0.25 | 2 (phone, website) | 0.15 |
| template_10091 (sale ad) | 0.20 | 1 (website) | 0.15 |

**Result:** template_831. Its website line keeps the sample text because the user gave no
website. The response mentions that, so the user can add one.

---

## 8. How we check it works

1. **Test list.** Write about 40 requests in English, Hindi and Marathi. For each, note
   which template or templates are a good answer. Include requests with and without
   phone numbers, websites and offers, and some where only one template holds every
   detail.
2. **Test command.** `python scripts/lido_match.py test` runs them all and prints:
   - how often the first pick is a good answer;
   - how often a good answer is in the top 3;
   - how often the "holds everything" rule was used, and whether it picked right;
   - every miss, with its scores.
3. **Tune.** Try other splits for the best-match path instead of 0.6 and 0.4, such as
   0.5/0.5 or 0.7/0.3, and keep the best.
4. **Goal.** The first pick is right at least 85 out of 100 times, and a right answer is
   in the top 3 at least 95 out of 100 times.

---

## 9. What changes in the code

| Where | Change |
|---|---|
| `backend/.venv` | Install the `embed` extra (command in §3). No `.env` change needed. |
| New `backend/app/lido_corpus/details.py` | The detail patterns, shared by templates and requests |
| New `backend/app/lido_corpus/match_index.py` | Part A: detail detection, card text, embeddings via the existing local embedder, the index file |
| `backend/app/lido_corpus/retrieval.py` | Part B: topic and details scores, the priority rule. Remove the "must be ready" rule. |
| `backend/app/api/schemas.py` + `frontend/src/pages/LidoTest.tsx` | Return and show the top 3, the path used, and missing details |
| `Makefile` | `lido-meta`, `lido-sync`, `lido-add` |

---

## 10. Template fixes already done in this session

These were found while preparing this plan and are already fixed:

- **Wrong roles.** Text layers with an empty type were marked "decoration", emails were
  "decoration", and big titles were "label". Now text is never decoration, emails get
  their own `email` role, websites and phones are also recognized from their sample
  text, and the largest text is the headline whatever its type.
- **Logo treated as a photo.** An untyped logo frame was sent for regeneration. Logos
  are now recognized from their image file too.
- **Scaled text measured wrong.** Text on scaled layers (template_10091) was measured as
  if unscaled, so its own copy "didn't fit". Now the layer's scale is applied.
- **Metadata corrected** in template_10091 (its round photo is an opaque room photo, not
  a cutout), template_1635, template_1789 and template_1825. Fresh hand-written metadata
  for the new template_831 (hair salon).
- **Reference notes** added to every template, so all are selectable today with the
  current code.
- **template_228 removed** (it was a copy of template_227).

---

## 11. Question for you

1. **Weights for the best-match path.** Start with 60% topic and 40% details?
