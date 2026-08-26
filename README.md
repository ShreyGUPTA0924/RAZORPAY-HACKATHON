# AgentFront

**The Merchant Agent-Readiness Engine.** Razorpay AI Buildathon 2026, Track 1.

Ingests a merchant's existing messy product catalog and generates their
complete agent commerce surface: structured attributes, a verified
compatibility graph, MCP tool endpoints, an AP2-aligned Cart Mandate
endpoint, and a gated payment path on Razorpay test mode.

Full thesis, architecture, and the tiered build plan: [`docs/CLAUDE.md`](docs/CLAUDE.md),
[`docs/agentfront-build-plan-v2.md`](docs/agentfront-build-plan-v2.md).

**Status:** Tier 0 (foundations) in progress.

## Quickstart

```bash
cp .env.example .env        # fill in keys -- see comments in the file
pip install -e ".[dev]"
docker compose up -d        # Postgres + Redis
python scripts/build_catalog.py        # regenerate data/catalog.json from data/raw/
```

## Repo layout

```
/pipeline/   the AI core: extraction, canonicalization, compatibility, quarantine
/surface/    generated per-merchant agent commerce surface (MCP, AP2 mandate, gate, payments)
/eval/       held-out ground truth, extraction eval, growth A/B harness, adversarial tests
/data/       raw catalog + curated data/catalog.json
/api/        FastAPI app
/frontend/   demo UI (later)
/scripts/    one-off / operational scripts (catalog curation, smoke tests)
/docs/       architecture and build-plan docs
```
