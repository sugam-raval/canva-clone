# How to design a template (read this before you start)

This is a checklist for designing templates that our system can fill automatically for
any business — a restaurant, a gym, a salon, a festival post, anything — using the same
template. Follow these rules and the AI-generated result will look clean and professional.
Skip them and the template will only really work for one type of business, or the text
may not fit, or colours may clash.

---

## 1. Keep decorations as shapes, not images

**Rule:** Anything decorative (borders, patterns, dividers, blobs, stripes, circles,
sparkles) should be a **shape**, not a flattened picture/icon.

**Why:** Shapes automatically change colour when a user picks their own colour theme.
Images never do — an image stays exactly as you drew it forever.

**Do:**
- A circle, blob, wave, stripe, gradient panel, dotted line, starburst.
- Simple geometric borders and frames.

**Don't:**
- A picture of a fork and knife, a dumbbell, a flower — anything that clearly
  *represents a real object from one specific industry.*

**Simple test:** Look at the decoration alone, with no text or photo around it. If you can
say "that's clearly a restaurant thing" or "that's clearly a gym thing" — it's not
generic enough, and it will look wrong when the same template is used for a different
business.

✅ Good: a soft gold circle behind the headline.
❌ Bad: a picture of a pizza slice behind the headline.

---

## 2. Use real text boxes, not text baked into an image

**Rule:** Every headline, subheading, body line, phone number, address, etc. must be an
actual **editable text layer** — never text that's part of a flattened image or graphic.

**Why:** Our system rewrites every text box automatically to match whatever the user
asks for. If text is baked into an image, it can never be changed — the design stays
stuck with your placeholder words forever.

**Do:** Type "Call us today: 000-0000" as a real text box.
**Don't:** Design that line in Photoshop/Illustrator and export it as one flat picture.

---

## 3. Only use real images for actual photos

**Rule:** Images/photos should only be used for things that are genuinely a photo —
a background scene, a product shot, a food photo, a person. Everything else
(decoration, borders, icons) should be shapes (see Rule 1).

**Why:** Photo slots get replaced automatically with a brand-new AI-generated photo
that matches the user's actual business — as long as the slot is clearly *just a photo
placeholder* and not mixed together with logos or decorations in the same image.

**Also important:**
- Keep the background photo, any product/subject photo, and the logo as **3 separate
  layers**. Never merge them into a single flattened image.
- Don't design a background photo where important decorations or text are painted
  directly into the photo itself — if the photo gets replaced, that decoration/text
  disappears with it.

---

## 4. Keep the logo separate and simple

**Rule:** The logo should be its own single layer, clearly a logo (not mixed with other
graphics), placed somewhere sensible (corner, header, footer).

**Why:** The logo is the one thing that's never regenerated — it gets swapped for the
business's real logo, exactly as-is, with no cropping or recolouring. If it's tangled
up with other design elements, swapping it will break the layout.

---

## 5. Leave breathing room for text of different lengths

**Rule:** Don't design a text box that only works for your exact placeholder words.
Assume the real text could be shorter or up to ~30–40% longer.

**Why:** A user's actual headline or offer text is rarely the same length as your
placeholder. If the box is too tight, text will get cut off or shrink to be unreadable.

**Do:**
- Leave extra vertical/horizontal space around text boxes.
- Test your layout by typing a noticeably longer sentence into each text box and make
  sure it still looks fine (or at least doesn't break the layout).

---

## 6. Keep the colour palette small and simple

**Rule:** Use at most 3–4 main colours in a template (plus black/white/neutral greys as
needed).

**Why:** When a user picks their own colour palette, our system maps your template's
colours onto theirs, one by one, by how prominent each colour is. Too many random
colours crammed in makes this mapping messy and the result muddy.

**Also:**
- Make sure text has strong contrast against whatever is behind it (a light colour on a
  light background, or dark on dark, will fail readability checks and get force-changed
  automatically — better to design it readable from the start).

---

## 7. Keep text and photos on separate layers from their background

**Rule:** Never assume a text box will always sit on the exact same coloured shape or
exact same part of a photo — but do design it so it clearly sits *on* a specific shape
(for automatic contrast-matching) or clearly *on* the open picture area (not on a busy,
detailed part of the photo).

**Why:** Our system checks contrast against whatever is directly behind each text box.
If text sits on a plain shape, that's easy to check and fix. If it sits over a very busy,
detailed part of a photo, contrast is harder to guarantee.

**Do:** Place important text over a plain sky, a soft blurred area, a solid-colour panel,
or a shape with a flat fill.
**Don't:** Place important text directly over small, highly-detailed objects in a photo
(e.g. right on top of a person's face or tiny cluttered objects).

---

## 8. Don't hardcode business-specific words into "fixed" labels

**Rule:** Even short labels/buttons ("Order Now", "Book a Table", "Shop Now") should be
normal, editable text boxes — not locked, not baked into a graphic.

**Why:** These get rewritten too ("Book Now" → "Join a Class", etc., depending on the
business). If they're locked or flattened into an image, the wrong wording will stay
stuck on designs for completely unrelated businesses.

---

## Quick checklist before you submit a template

- [ ] All decorations are shapes (no icons/graphics that scream one specific industry)
- [ ] All text is real, editable text boxes — nothing baked into an image
- [ ] Background photo, subject/product photo, and logo are 3 separate layers
- [ ] Logo is clean, isolated, not mixed with other graphics
- [ ] Text boxes have extra room for longer/shorter text
- [ ] No more than ~3–4 main colours used
- [ ] Text has clear contrast against whatever sits behind it
- [ ] Important text isn't sitting on a busy/cluttered part of a photo
- [ ] No label/button text is locked or flattened into a graphic

If every box above is checked, the template will work well for many different
businesses, not just the one you had in mind while designing it.
