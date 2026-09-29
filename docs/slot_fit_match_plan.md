# Plan: pick a template that can hold ALL the text the user asked for

Status: **implemented** (2026-09-29). Builds on `docs/new_match_plan.md`.
Code: `backend/app/lido_corpus/fit.py` (new), `matcher.py`, `retrieval.py`,
`generate_ai.py`, `pipeline.py`, `model.py` / `loader.py` (`optional`), API schemas and
`frontend/src/pages/LidoApp.tsx`. Check with `python scripts/lido_match.py show "..."` and
`python scripts/lido_match.py test`.

Differences from the proposal below:
- **Slot profiles are computed at match time, not stored.** `fit.slot_fits` builds them
  from the template itself (cached per template version). Fitting all 18 templates takes
  about 70 ms. No database change and no `CARD_VERSION` bump were needed.
- **No minimum topic for tier A** (question 2). With it, a template that placed all 5
  hiring lines lost to one that dropped 2 job titles. A template that places everything
  now always ranks first, which is the same as the old "holds every detail" rule.
- **`max_chars` tolerance: 10%** (question 1), and only when the slot has `max_lines` and
  the real font file is available to measure the wrap.
- **Empty contact slots are reused only when marked `optional`** (question 3). No
  template sets it yet: whether a design still looks right without its website line
  needs a look at the render, template by template.
- **Too many lines:** the least important lines are dropped and reported (question 4).
  The fill model is told it may use a shorter version of a dropped line in a free layer.
- **A split line is placed whole or not at all.** "Made Daily" alone, without the rest
  of its tagline, is not what the user wrote.
- **Real-font measurement.** Measuring in the real font shows template_227 cannot hold
  "WEEKEND PIZZA FEST": "WEEKEND" is too wide for its headline box. The worked example in
  §10 assumed it could. On today's corpus the pizza request goes to template_1825, the
  only template that places all 5 lines unchanged.
- **Implied items** (§5.3, lines the user did not quote) are not added yet. Requests
  without quoted lines are matched on their details alone, as before.
- Regression run (`lido_match.py test`, same corpus, LLM on): old code 24/28 first pick,
  28/28 top 3. New code 25/28 first pick, 27/28 top 3, and 4/4 quoted-line cases fully
  placed. The 3 misses that remain are shared with the old code and come from test
  expectations written before newer templates (template_4, template_7347) were added.

---

## 1. The problem, with a real run

Request (shortened):

> Promotional ad for a modern Italian restaurant, hero cheesy pizza …
> Include the text: “WEEKEND PIZZA FEST” “BUY 1 GET 1 FREE”
> “Freshly Baked • Extra Cheesy • Made Daily” “Order Now” “Limited Time Offer”

`python scripts/lido_match.py show "…"` today:

```
Topic   : Promotional advertisement for a modern Italian restaurant
Details : offer
Path    : holds every detail
  1. template_227     score 0.66  topic 0.71  details 1.00  placeholder website
  2. template_7347    score 0.54  topic 0.59  details 1.00  placeholder email
  3. template_10091   score 0.51  topic 0.56  details 1.00  placeholder website
```

The user asked for **5 exact lines**. template_227 has 5 text slots, but one of them is a
website slot:

| template_227 slot | limit | sample text | what happens today |
|---|---|---|---|
| headline | 24 chars, 2 lines | Healthy Food | WEEKEND PIZZA FEST ✓ |
| subhead | 30 chars, 4 lines | Limited Happy Hours Promo | BUY 1 GET 1 FREE ✓ |
| body | 40 chars, 2 lines | Healthy but Tasty Diet? | the 41-char tagline is over the limit, so `clamp_text` trims it to "Freshly Baked • Extra Cheesy • Made" ✗ |
| label | 20 chars | Get Yours! | Order Now ✓ |
| website | 30 chars | www.yourwebsite.com | the placeholder is kept (the user gave no website) ✗ |
| — | — | — | "Limited Time Offer" has **no slot** and is lost ✗ |

The result is one line dropped, one line cut short, and a fake website on the design.
The matcher also reported this pick as "holds every detail".

## 2. Why it happens (root causes)

1. **The matcher only knows 7 "details"** (phone, email, website, address, offer, price,
   date). It never counts **how many lines** the user asked for, how **long** they are,
   or what **kind** they are (headline, tagline, button, badge). Here only `offer` was
   found, so 3 templates tied at "holds everything" and the topic decided.
2. **Slot capacity is never checked at match time.** `max_chars` / `max_lines` are only
   used *after* the pick, in `generate_ai.check_text`.
3. **The fill step decides placement on its own.** The fill LLM is told "you never
   add, remove, merge layers" and "write copy for every layer". So when there are more
   lines than slots, it silently picks which line to lose.
4. **User text is not protected.** The repair call rewrites text that is too long with
   "shorter words", and `clamp_text` drops the last words. Both happen even when the text
   is the user's exact quote.
5. **An empty contact slot can only keep its placeholder.** `_accept_text` puts back
   `www.yourwebsite.com` when the user gave no website. It cannot be hidden or reused.

## 3. The idea in one paragraph

Treat matching as **"can every piece of content go into a slot where it fits?"**, not
just "does it have the right detail types?". We turn the request into a list of
**content items**, each with a kind, the exact text if the user quoted it, and a
length. We turn each template into a list of **slots**, each with the kinds it accepts
and its real capacity. Then we solve a small **assignment problem** (items → slots)
for each template. The templates that place every item without cutting it win, ranked
by topic. The winning assignment is then **handed to the fill step**, so the text lands
where the matcher planned and user quotes are never rewritten.

```
request ──► content items ─┐
                           ├─► assignment per template ─► tiers + topic ─► best template
template ──► slot profile ─┘                                                   │
                                                                               ▼
                                       fill step gets the slot plan (quotes locked)
```

---

## 4. Part A — Slot profile per template (built with the index)

Extend `TemplateDetails` in `details.py` with one `SlotProfile` per editable text slot:

```python
@dataclass
class SlotProfile:
    layer_id: str
    role: str                 # headline / subhead / body / label / website / phone / …
    accepts: dict[str, float] # content kind → placement cost (0 = perfect, 0.5 = ok)
    max_chars: int | None
    max_lines: int | None
    chars_per_line: int | None   # from textfit measure, same as TextTarget.chars_per_line
    list_group: int | None       # id of a list group (from _list_items), else None
    contact: str | None          # "website" etc. for contact slots
```

**What each slot accepts** comes from its role plus its sample text. This is the same
signal `_slot_details` and `_is_button_text` already use:

| slot | accepts (cost) |
|---|---|
| headline | headline 0, brand 0.3, offer 0.4 |
| subhead | tagline 0, offer 0 *if sample text is an offer*, badge 0.2, headline 0.5 |
| body | tagline 0, body 0, feature 0.3, offer 0.5 |
| body in a list group | feature 0, tagline 0.5 |
| label with button text ("Order Now", "JOIN NOW") | cta 0 |
| label with offer text ("25% off") | offer 0, badge 0.2 |
| other label | badge 0, cta 0.2, feature 0.3 |
| contact slot (website/phone/email/address) | its own contact kind 0 |
| contact slot the user left empty | badge 0.5, cta 0.5 (**reuse**; see §7) |

Store the profile in the same `lido_templates` row as `details` (JSON column). Bump
`CARD_VERSION` so every row is rebuilt once. The card text does not have to change.

## 5. Part B — Content plan per request (same LLM call as today)

`profile_request` already makes one fast LLM call. Add one field to
`RequestProfileOutput`:

```python
class ContentItem(BaseModel):
    kind: Literal["headline", "tagline", "offer", "price", "cta", "badge", "feature",
                  "body", "brand", "date", "phone", "email", "website", "address"]
    text: str | None     # the exact words when the user asked for this text, else None
    verbatim: bool       # True = the user asked for exactly this text

content: list[ContentItem]
```

Rules, so the result is predictable:

1. **Quoted text is found by code first.** A regex pulls out every `“…”`, `"…"`,
   `'…'` and every line under "Include the text:". Each one becomes a verbatim item.
   The LLM only labels the *kind*. As with `_verified` today, an LLM item whose `text`
   is not really in the prompt is thrown away.
2. **Contact, price and date items come from the existing detection.** `details_in_text`
   and `_verified` still run, and each found detail becomes an item. So the 7-detail
   logic becomes a special case of this plan, not a second system.
3. **Implied items** (no quotes: "a flyer for my bakery, 20% off this weekend") get
   `verbatim=False`. The writer can shorten them, so they have no length limit. They
   still count, so a brief that implies headline + offer + cta avoids 2-slot templates.
4. **Splittable items.** A verbatim item that contains `•`, `|`, `·` or a line break
   also gets split versions. "Freshly Baked • Extra Cheesy • Made Daily" can be one
   tagline or three features.

Each item gets a **weight**, which says how bad it is to lose it:

| kind | weight |
|---|---|
| headline, offer, price, contact details | 3 (must keep) |
| cta, date | 2 |
| tagline, badge, brand | 1.5 |
| feature (each), body | 1 |
| any implied (non-verbatim) item | × 0.5 |

Pizza request → items:

| # | kind | text | chars | weight |
|---|---|---|---|---|
| 1 | headline | WEEKEND PIZZA FEST | 18 | 3 |
| 2 | offer | BUY 1 GET 1 FREE | 16 | 3 |
| 3 | tagline (splittable into 3 features) | Freshly Baked • Extra Cheesy • Made Daily | 41 | 1.5 |
| 4 | cta | Order Now | 9 | 2 |
| 5 | badge | Limited Time Offer | 18 | 1.5 |

## 6. Part C — Fit: solve the assignment for each template

For each template, build a cost matrix with **items as rows** and **slots + one "drop"
column per item** as columns:

- `cost(item, slot) = accepts[item.kind]`, or **∞** when the slot does not accept that kind.
- **Length check (verbatim items only):** the item must satisfy `len ≤ max_chars`, and its
  measured wrap in the slot's real font (`textfit.wrap`, the same check as
  `check_text`) must fit `max_lines`. If not, the cost is **∞**. We never place user
  text where it would be cut.
- `cost(item, drop) = weight × 10`, so dropping is always the last resort, and a heavier
  item is dropped last.
- Split versions: a splittable item is tried both whole and split. The split version
  needs as many free slots in one `list_group` as it has parts. Keep whichever costs less.
- Merge (optional, phase 2): a badge or cta can share a multi-line slot with the offer
  when the combined text fits (cost 0.4). Example: "BUY 1 GET 1 FREE / Limited Time".

Solve with `scipy.optimize.linear_sum_assignment` (scipy 1.17 is already in
`backend/.venv`). The matrices are at most about 12 × 25, so this takes microseconds
per template. With 18 templates we solve all of them. When the corpus grows into the
thousands, first take the top 50 by pgvector topic score, then solve only those.

What we get back for each template:

```python
@dataclass
class Fit:
    placed: dict[int, str]       # item index → layer_id
    dropped: list[int]           # items with no slot
    coverage: float              # Σ weight placed ÷ Σ weight given
    must_keep_ok: bool           # every weight-3 item placed
    fit_cost: float              # mean placement cost of placed items (0..1)
    leftover_slots: list[str]    # slots with no item — the writer will fill them
    leftover_contact: list[str]  # contact slots with no user value
    leftover_offer: list[str]    # offer/price-looking slots with no user offer (risky, §7)
```

## 7. Part D — The new priority rule (replaces `rank` in `matcher.py`)

Three tiers. A template is only compared with others in the **same tier**, and a
higher tier always wins:

| tier | condition | ranked by |
|---|---|---|
| **A — fits everything** | no item dropped | `topic − 0.15·fit_cost − penalties` |
| **B — keeps the must-keeps** | every weight-3 item placed | `0.5·topic + 0.4·coverage + 0.1·(1 − fit_cost) − penalties` |
| **C — best effort** | everything else | same formula as B |

Penalties (small, same idea as today's `EMPTY_CONTACT_PENALTY`):

- `0.05` for each **leftover contact slot** that cannot be hidden. If the slot is hidden
  or reused, there is no penalty.
- `0.08` for each **leftover offer/price slot**. The writer would have to invent a
  "25% off" the user never gave, so these must stay empty or be rewritten into
  non-factual copy.
- `0.02` for each **leftover generic slot**, plus `0.05` more when
  `leftover_slots > len(items)`. This stops a 10-slot template from winning a
  2-line request with 8 invented lines.

`TIE_MARGIN` stays. On a near-tie, the higher `coverage` wins, then the lower `fit_cost`.

**Empty contact slots — hide or reuse.** Add an optional metadata flag
`slot.optional: bool` (hand-set per `docs/TEMPLATE_METADATA_RULES.md`). It means "this
layer can be removed and the design still looks right". With the flag, a contact slot
the user left empty is **hidden** instead of showing `www.yourwebsite.com`. It may also
take a short badge or cta, the "reuse" line in §4. Reuse is only allowed when it is the
only way to place a verbatim item.

`MatchResult.to_json` gains `tier`, `coverage`, `dropped` (the text of every item that did
not fit) and `plan` (item → layer_id). The Lido test page shows them the same way it shows
`missing` today.

## 8. Part E — Hand the plan to the fill step

This part prevents drops *after* the match. Today the fill LLM re-decides placement.

1. `generate_template_fill(…, plan=result.best_plan)`. For each placed verbatim item,
   the slot payload gets `"locked_text": "<exact user text>"`. The system prompt says:
   *locked_text must be returned exactly; write copy only for layers without it.*
2. `_accept_text`: for a locked slot, keep the planned text whatever the model returned.
3. The repair call and `clamp_text` **skip locked slots**. The matcher already checked
   that the text fits (§6), so a locked slot can never fail `check_text`. If one does,
   the font measure differs, and we log `lido.template_fill.locked_overflow` instead of
   cutting user text.
4. Leftover slots are written by the LLM as today. Leftover offer/price slots get the
   note "no offer was given — write a non-numeric supporting phrase". Leftover `optional`
   contact slots are hidden (empty text / layer removed in `compose.py`).
5. The response lists `dropped` items, so the UI can say: *"'Limited Time Offer' didn't
   fit this template"*. Losing text is then never silent.

## 9. Part F — When no template fits everything

This will keep happening while the corpus is 18 templates. Handle it in order:

1. **Tier B/C pick with an honest report.** The response names every dropped line.
2. **Offer the next-best alternatives.** The top 3 already come back. Show the tier and
   what each one drops, so the user can switch with one click (`template_id` override).
3. **Corpus gap log.** When the best pick is not tier A, log
   `lido.match.gap {kinds, lengths, topic}`. A weekly look at this log shows exactly
   which templates to add. For example: "food promo with headline + offer + tagline +
   cta + badge".
4. (Later) **Let the user choose**: "drop a line" or "shorten a line with AI". Shortening
   means turning a verbatim item into a non-verbatim one, with the user's consent only.

---

## 10. The pizza request, end to end with the new rule

*Placements are worked out by hand from the real slot limits. Topic scores for 227 and
7347 are from today's run; the others are estimates. Re-check with
`lido_match.py show` once it is built.*

| template | topic | placement | dropped | tier |
|---|---|---|---|---|
| template_227 (restaurant) | 0.71 | 1→headline, 2→subhead, 4→label, 5→website slot (reuse, if `optional`) | #3 tagline: 41 chars, body limit 40; no list group to split into | **B** |
| template_990 (fitness) | ~0.30 | 1→headline, 2→body (0.5), 3 split → 3 list bodies, 4→label, 5→email slot (reuse) | none, but offer slot "25% off" is left over | **A** (weak topic, leftover-offer penalty) |
| template_7347 (juice promo) | 0.59 | 4→label "Order Now" | #1 (headline 14 < 18), #2 (offer slot 13 < 16), … | C |
| template_9483 (product launch) | — | 2 slots only | 3 items | C |

What the new rule shows:

- Today's pick (227) **really drops a line**, and the new rule reports it instead of
  calling it "holds every detail".
- Strictly, only a template that fits everything would win. Here that is template_990,
  a fitness layout with an offer squeezed into a list row. That is a sign of a **corpus
  gap**, not a good design. So we need two safety valves:
  - a **minimum topic for tier A**. A tier-A template with `topic < 0.35` competes in
    tier B instead. Tune this with the test set.
  - **a tolerance decision for `max_chars`** (question 1 below). If a verbatim item may
    run up to 10% over `max_chars` when its *measured* wrap still fits `max_lines`,
    227 holds all 5 lines and wins cleanly in tier A.
- Either way, the gap log records "restaurant promo, 5 lines: headline/offer/tagline/
  cta/badge". Adding one food template with those slots fixes this whole class of request.

---

## 11. What changes in the code

| where | change |
|---|---|
| `details.py` | `SlotProfile`, `slot_profiles(meta)`, the accepts table (§4). Quote extractor `quoted_lines(prompt)` (§5.1). |
| `match_index.py` | keep the slot profiles in `IndexEntry.details`; bump `CARD_VERSION` |
| `store.py` | save/load the profiles with `details` (JSON, no new column) |
| `matcher.py` | `ContentItem` in `RequestProfileOutput`; new `fit.py` (or a section) with the cost matrix and `linear_sum_assignment`; new `rank` with tiers A/B/C (§7); `MatchResult` gains `tier`, `coverage`, `dropped`, `plan` |
| `retrieval.py` | `ScoredTemplate.match.best_plan` passed on |
| `pipeline.py` → `generate_ai.py` | `plan` argument, `locked_text` in the payload, lock rules in `_accept_text` / repair / `clamp_text`, hiding `optional` empty contact slots (§8) |
| `model.py` + `docs/TEMPLATE_METADATA_RULES.md` | `SlotInfo.optional: bool = False` |
| `api/schemas.py` + `frontend/src/pages/LidoTest.tsx` | show tier, coverage, dropped lines |
| `match_cases.jsonl` | new field `"must_place": [...]`: the lines that must all appear |

## 12. How we check it works

1. **New test cases** in `match_cases.jsonl`: at least 15 requests with quoted text
   (2, 4, 5 and 7 lines; long taglines; bullet lists with `•`; Hindi quotes). Include this
   pizza request.
2. `lido_match.py test` also reports:
   - **placement rate**: the share of verbatim lines that got a slot (goal: 100% in tier A,
     and every miss is listed);
   - **silent drops**: verbatim lines missing from the final fill that were *not* in
     `dropped`. This must be **0**, and it is checked by running the fill in a test with a
     stubbed LLM.
   - the old top-1 / top-3 accuracy, which must not fall below today's 28/28.
3. Unit tests for the assignment: a verbatim item that is too long → ∞ cost → dropped
   rather than cut; a split into a list group; contact reuse only with `optional`.
4. Tune the costs and weights, the tier-A minimum topic, and the penalties with the test set.

## 13. Questions to decide

1. **`max_chars` tolerance for user text.** Allow up to 10% over when the measured wrap
   still fits `max_lines`? This makes 227 hold the pizza tagline.
2. **Minimum topic for tier A:** start at 0.35?
3. **Reuse of empty contact slots** for a badge or cta: allowed only with `optional: true`,
   or never?
4. **Too many lines for any template:** drop the lowest-weight line (default), or ask the
   user before generating?
