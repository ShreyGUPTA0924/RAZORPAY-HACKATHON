# AgentFront

**The Merchant Agent-Readiness Engine.** Razorpay AI Buildathon 2026, Track 1.

Ingests a merchant's existing messy product catalog and generates their
complete agent commerce surface: structured attributes with per-field
confidence, a verified compatibility graph, MCP tool endpoints, an
AP2-aligned mandate chain, and a gated payment path on Razorpay test mode.

Start here: [`docs/architecture.md`](docs/architecture.md) (the AP2 mandate
chain, the LLM-proposes/code-verifies boundary, and where NPCI's UAP fits),
[`docs/what-broke.md`](docs/what-broke.md) (every real bug this project found
in its own tooling, and how each was caught), [`docs/refusal_codes.md`](docs/refusal_codes.md).
Full thesis and tiered build plan: [`docs/CLAUDE.md`](docs/CLAUDE.md),
[`docs/agentfront-build-plan-v2.md`](docs/agentfront-build-plan-v2.md).

**Status:** the AI core (extraction, confidence-gated quarantine,
canonicalization, compatibility proposal+verification) and the full
transaction surface (AP2 mandate verify/issue, deterministic gate,
idempotency, refusal taxonomy, Razorpay test-mode payments, MCP server) are
built and tested against the real catalog. The before/after growth harness
and an independent adversarial red-team have both been run for real, with
results committed under `eval/`. A four-screen frontend demo
(`frontend/`) is built and replays those real, committed results —
extraction, the generated surface, a scripted agent transaction, and the
growth/adversarial numbers — entirely client-side; it does not call the
Python backend live (see its own note below). The FastAPI app (`api/`) has
not been started — there is currently no live API layer connecting the
frontend to the backend at all; they are two separate, independently-tested
things today, not one running system.

## Quickstart

Tested from a genuinely clean clone (fresh directory, fresh venv) before
being written down here — see the commit that added this section for the
verification.

```bash
git clone <this repo> && cd agentfront
python -m venv .venv && source .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

cp .env.example .env
# Required even to run the test suite fully: generate an Ed25519 signing
# seed and put it in .env as MANDATE_SIGNING_SEED. Without it, every test
# that issues a Cart Mandate fails at RuntimeError, not silently.
python -c "import nacl.signing,binascii; print(binascii.hexlify(nacl.signing.SigningKey.generate()._seed).decode())"
# -> paste the output as MANDATE_SIGNING_SEED=... in .env

docker compose up -d     # Postgres + Redis. Only Redis is used by anything built so far
                          # (mandate nonce replay, payment idempotency, MCP order state) --
                          # Postgres is provisioned for the future API layer, nothing reads
                          # or writes it yet.

pytest -m "not llm"      # 267 passed, 1 skipped (needs a real Razorpay test key), 6 deselected
```

No `GOOGLE_API_KEY` / `GROQ_API_KEY` / `RAZORPAY_KEY_ID` needed for any of the
above — the full test suite runs against real Redis and real (committed)
catalog data, with every LLM call either mocked or gracefully skipped without
a key.

## Frontend demo

```bash
cd frontend
npm install
npm run dev              # prints the local URL, typically http://localhost:5173/
```

Open the printed URL and step through Extraction → Surface → Agent mode →
Results. Everything on every screen replays real, committed data from
`eval/` client-side — no backend process, no API keys, no live LLM or
Razorpay calls. **This is a deliberate design choice** (a deterministic demo
that can't fail mid-recording), not a placeholder for a missing
integration — but it means "Run session" in Agent mode plays back a
scripted transaction shape, not a live one. The header's "Replaying from
cache" badge and the payment step's own "simulated" label both say this
explicitly; see `docs/what-broke.md` for the specific, current limitation
this implies for Razorpay capture.

## What runs right now with zero API keys

Everything below reads the catalog and the already-computed, committed
results under `eval/` — no LLM calls, no quota spent:

```bash
# The generated MCP surface, live against the real 60-SKU catalog
python -c "from surface.mcp_server import get_capability_manifest; import json; print(json.dumps(get_capability_manifest(), indent=2))"
python -c "from surface.mcp_server import search_catalog; import json; print(json.dumps(search_catalog(category='charger'), indent=2))"

# Inspect real, committed run results
cat eval/extraction_results.json          # 60/60 SKUs, per-field confidence + quarantine decisions
cat eval/growth_ab_results.json           # before/after growth harness -- raw catalog vs. this surface
cat eval/adversarial/adversarial_results.json   # independent red-team run, what got through
cat eval/canonicalization_results.json    # model_compat clustering + every LLM adjudication made
cat eval/compat_results.json              # compatibility proposals + verification against real attributes

pytest -m "not llm"                       # full suite, real Redis, real crypto, no LLM
```

## What needs API keys

Re-running any pipeline stage's LLM call for real (rather than reading the
committed results above) needs `GOOGLE_API_KEY` and/or `GROQ_API_KEY` in
`.env` — see `pipeline/llm_config.py` for exactly which component uses which
provider by default, and `.env.example` for the per-component override
pattern (useful if a provider's free-tier quota is exhausted; every provider
here has a real daily limit, hit repeatedly during this build — see
`docs/what-broke.md`'s infrastructure section for the specifics):

```bash
python -m pipeline.extract                        # attribute extraction, disk-cached, batched
python -c "
import json
from pipeline.canonical import canonicalize_model_compat_values
data = json.loads(open('eval/extraction_results.json', encoding='utf-8').read())
values = [m for r in data for m in (r['attributes']['model_compat']['value'] or [])]
result = canonicalize_model_compat_values(values)
print([c for c in result.clusters if len(c) > 1])
"                                                    # model_compat clustering, disk-cached adjudication
python -m pipeline.compat                          # compatibility proposal + verification
python -m eval.growth_ab                            # before/after growth harness
python -m eval.adversarial.harness                  # independent adversarial red-team
```

The real Razorpay test-mode smoke test additionally needs `RAZORPAY_KEY_ID` /
`RAZORPAY_KEY_SECRET` (test-mode keys, `rzp_test_...` — `surface/payments.py`
refuses to run against anything else):

```bash
python scripts/razorpay_smoke.py
pytest tests/test_payments.py -k real_api    # the one test that's skipped above without a key
```

## Repo layout

```
/pipeline/          the AI core
  extract.py         attribute extraction + per-attribute confidence, batched, disk-cached
  extract_cache.py    content-addressed disk cache backing extract.py
  canonical.py        model_compat canonicalization: embedding clustering + LLM adjudication
  compat.py           LLM proposes compatibility edges from raw text
  verify.py            code VERIFIES proposals -- NO LLM IMPORTS
  quarantine.py        confidence-gated publish decision -- NO LLM IMPORTS
  llm_config.py / llm_clients.py   provider routing, fallback chains
/surface/            generated per merchant
  mandate.py            AP2 intent verify + cart mandate issue -- NO LLM IMPORTS
  gate.py                ALLOW / REFUSE(code) / ESCALATE, pure function -- NO LLM IMPORTS
  refusal.py             structured refusal taxonomy (13 codes, see docs/refusal_codes.md)
  idempotency.py         Redis, keyed on hash(intent_mandate_id + cart_hash)
  payments.py            Razorpay test-mode order/capture, strictly behind the gate
  mcp_server.py          search / get_product / check_availability / create_cart_mandate / ...
/eval/
  ground_truth/          hand-labelled, held-out, never tuned against
  extraction_eval.py       precision / recall / F1 per attribute
  growth_ab.py              before/after harness -- raw catalog vs. generated surface
  adversarial/               independently-generated attacks + real execution against the stack
  *.json                      committed results from real runs -- see "zero API keys" above
/data/               raw source + curated data/catalog.json (caches are gitignored, not committed)
/scripts/            one-off / operational scripts (catalog curation, Razorpay smoke test)
/tests/              pytest suite -- mocked LLM calls, real Redis, real Ed25519 crypto
/docs/               architecture, what actually broke, refusal code table, build plan
/frontend/           React + TS + Tailwind demo -- replays committed eval/ results, no live backend call
  src/data/            fixtures pulled from real eval/*.json, not invented
  src/components/      layout/ catalog/ extraction/ agent/ metrics/ ui/
/api/                empty -- no FastAPI app yet, no live link between frontend and backend
```
