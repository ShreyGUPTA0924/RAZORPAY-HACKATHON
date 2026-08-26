# Tier 0 kickoff prompt — paste into Claude Code

> Paste this **after** you have placed `CLAUDE.md` and `docs/build-plan.md` in
> the folder, and after you have downloaded the raw dataset into `data/raw/`.

---

Read `CLAUDE.md` and `docs/build-plan.md` first — they define the project
thesis, the architectural rules, and the tiered plan. Everything below is
Tier 0 only. Do not start Tier 1.

I have placed a real, messy product-listing dataset at `data/raw/`. It is
genuine e-commerce data with inconsistent titles, attributes buried in prose,
and missing fields.

Build Tier 0, in this order:

**1. Project scaffold**
Create the full directory structure exactly as specified in `CLAUDE.md`.
Add `pyproject.toml` (or `requirements.txt`), `.gitignore` (must exclude
`.env`), `.env.example` listing every key the project will need, and a
`README.md` stub. Add a `docker-compose.yml` bringing up PostgreSQL and Redis.
Verify it comes up cleanly.

**2. Catalog selection and shaping**
Inspect the raw dataset. Select ONE narrow product category with natural
accessory relationships — phones plus cases, screen protectors, chargers, and
earbuds is the target if the data supports it. Pick roughly 60 SKUs:
- ~40 that are messy but parseable
- ~15 with significant missing or ambiguous fields
- ~5 that are genuinely unparseable (these should end up quarantined)

Write these to `data/catalog.json` preserving the original messy text
**verbatim**. Do not clean, normalize, or enrich anything — the mess is the
input to the problem. Print a short report of what you selected and why.

**3. Ground-truth harness (scaffold only — I label it myself)**
Choose 20 SKUs from the set as the held-out evaluation set. Generate
`eval/ground_truth/labels_template.json` containing, for each of those 20:
the SKU id, the raw title and description, and an empty structured-attribute
object with all target attribute keys present and set to null.

**Do not fill in any values.** Do not infer, suggest, or pre-populate labels.
I will hand-label this file myself from the raw text. Also write
`eval/ground_truth/README.md` stating that these labels are hand-written,
held out, and must never be revised after seeing pipeline output.

**4. Attribute schema**
Define the target attribute schema as Pydantic models in
`pipeline/schema.py` — the canonical attribute set for this category
(port type, wattage, screen dimensions, model compatibility, wireless
charging, material, etc.), each with a confidence field. Include the
canonical enum vocabularies. This schema is the contract the whole pipeline
is built against, so keep it tight and well-commented.

**5. Razorpay connectivity smoke test**
Write `scripts/razorpay_smoke.py` that, using test-mode keys from `.env`,
creates an Order and confirms a capture path works. Keep it isolated and
obvious. I need to know on day one that payments work.

**6. LangSmith tracing setup**
Wire tracing configuration now, not later, so every subsequent call is traced.

When done, print a checklist of what exists, what I still need to do manually,
and anything in the dataset that surprised you or that might undermine the
extraction problem being genuinely hard.

Do not begin extraction, canonicalization, or compatibility work.
