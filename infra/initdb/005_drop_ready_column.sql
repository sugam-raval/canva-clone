-- The reference_note review-tracking concept is gone: every template with a `meta`
-- block is already a match candidate regardless of review status (see retrieval.py),
-- so the `ready` column it fed was purely informational and is dropped. Idempotent.

alter table lido_templates drop column if exists ready;
