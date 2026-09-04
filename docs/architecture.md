# Architecture

AgentFront ingests a merchant's existing, messy catalog and generates the
complete surface an AI buyer agent needs to transact against it: structured
attributes, a verified compatibility graph, MCP tool endpoints, an
AP2-aligned mandate chain, and a gated payment path on Razorpay test mode.
This document explains the two structural decisions everything else follows
from — the mandate chain, and the LLM/code boundary — plus where the India
rail (NPCI's UAP) fits.

---

## 1. The AP2 mandate chain, and which half of it we are

AP2 (Google's Agent Payments Protocol) chains three signed artifacts:

```
Intent Mandate  --->  Cart Mandate  --->  Payment Mandate
(buyer agent          (merchant)          (payment network)
 issues, signs)
```

- **Intent Mandate**: issued and signed by the *buyer agent*, with its own
  Ed25519 keypair. It states what the buyer authorized — a price ceiling
  (`max_amount`), a category scope (`allowed_categories`), an expiry, and a
  nonce for replay protection. Nothing about it is trusted by the merchant
  until independently verified.
- **Cart Mandate**: issued and signed by the *merchant*, binding specific
  SKUs and a computed total to one already-verified Intent Mandate. This is
  the artifact AgentFront actually produces.
- **Payment Mandate**: the leg the payment network sees. Out of scope for
  this build (see Tier 4 future work) — Razorpay test-mode order/capture
  stands in for it here.

**AgentFront is the merchant side of this chain, and only the merchant
side.** Concretely, that maps onto the codebase as:

| AP2 concept | This codebase |
|---|---|
| Intent Mandate verification (signature, expiry, nonce replay) | `surface/mandate.py: verify_intent_mandate()` |
| Policy checks against the *proposed cart* (price ceiling vs. total, category scope vs. requested SKUs) | `surface/gate.py: evaluate()` — deliberately a separate function from mandate verification; the gate receives the verification *result* as a plain argument rather than re-deriving it |
| Cart Mandate issuance | `surface/mandate.py: issue_cart_mandate()` — signs with the merchant's own key, only ever called after `gate.evaluate()` returns `ALLOW` |
| Duplicate-execution protection | `surface/idempotency.py`, keyed on `hash(intent_mandate_id + cart_hash)` — distinct from nonce replay, which is a mandate-level guard against reusing the *same* Intent Mandate twice. Idempotency guards a different failure mode: an already-verified mandate whose *payment execution* gets retried (an LLM agent retrying non-deterministically after a dropped response, for instance) |
| Payment Mandate / network leg | Not built. `surface/payments.py` wraps Razorpay test-mode order-create + capture directly behind the gate as a stand-in |

The Intent Mandate is untrusted input **throughout** — not just at the
signature-verification step. `surface/gate.py` re-checks price ceiling and
category scope against the actual proposed cart on every call; nothing
upstream is trusted to have already enforced policy correctly. See
`docs/what-broke.md`'s cumulative-ceiling-bypass entry for a real gap this
same untrusted-input posture surfaced: nonce replay and idempotency each
correctly guard the transaction they were built to guard, but neither
tracks *cumulative* spend across several distinct transactions under one
mandate — a reminder that "untrusted input" has to be re-examined at every
layer a new capability is added, not assumed solved once.

---

## 2. "The LLM does hard inference. Deterministic code does money, and
   verifies every LLM claim before it can affect a transaction."

This is the single non-negotiable rule the rest of the pipeline is built
around (`docs/CLAUDE.md`'s architectural rules, #1). It shows up as a
literal, enforced pattern — LLM proposes, code verifies — at every layer
that touches untrusted or LLM-derived data, not just as a slogan:

**Extraction → quarantine.** `pipeline/extract.py`'s LLM call proposes a
value *and* a confidence for every attribute. `pipeline/quarantine.py` (zero
LLM imports, enforced literally and checked via grep every time a file in
this area changes) is the only thing that decides what actually gets
published — any field below `CONFIDENCE_THRESHOLD` is redacted regardless of
what the LLM proposed, and `accessory_type` specifically gates whether
*anything* about a SKU is safe to publish, since every other field's
applicability depends on knowing what kind of product this even is.

**Canonicalization: embeddings propose candidates, an LLM adjudicates, code
enforces the invariant.** `pipeline/canonical.py` is a three-layer version of
the same pattern, not a two-layer one: local embedding search proposes
*candidate* near-duplicate pairs (zero LLM quota — this layer never decides
anything, only narrows what's worth asking about), an LLM adjudicates each
candidate pair with a real yes/no/not-confident call, and a deterministic
constraint — never let a transitive chain of "same" merges connect two
values the LLM confidently called "different" on some other pair — sits on
top of *both* of them. That third layer exists because of a real, caught bug
(see `docs/what-broke.md`): even LLM-adjudicated merges can chain into a
contradiction if nothing checks for it afterward. Proposing and verifying
is necessary but not sufficient; the composition of many individually-correct
verified decisions can still be wrong, and something has to check that too.

**Compatibility: proposal and verification are architecturally separate
files, on purpose.** `pipeline/compat.py` (LLM proposes an edge from raw
catalog prose) and `pipeline/verify.py` (zero LLM imports, checks a proposal
against a SKU's own already-extracted attributes) are split into two files
specifically so the boundary is visible in the file tree, not just in code
review. `verify.py`'s `verify_model_compat_match()` will *reject* a proposal
that is textually correct but phrased in a different canonical convention
than extraction happened to use — a real, measured 68% precision on a live
run, root-caused and documented rather than papered over by loosening the
verifier (`docs/what-broke.md` again). That strictness is deliberate:
`verify.py` also gates real payment-affecting compatibility claims, so the
right place to close a canonicalization gap is upstream, in
`canonical.py` — never by making the verifier more permissive.

**Mandates: the buyer proposes (by signing), the gate decides.** An Intent
Mandate is, structurally, a *proposal* — "I am authorizing this" — signed
by a party (the buyer agent) this system does not control and must not
trust by default. `surface/gate.py` is the deterministic verifier: pure
function, fixed argument order, no I/O of its own, ALLOW/REFUSE/ESCALATE as
its only three outputs, near-full branch coverage in tests. The refusal
taxonomy (`surface/refusal.py`) makes *why* a proposal was rejected a
first-class, machine-readable value, not a string an LLM would have to be
trusted to interpret consistently.

The common thread: **wherever an LLM produces a claim that could affect
what gets published or what money moves, that claim passes through a
separate, deterministic, LLM-free check before it can act** — and that
check's file has no LLM imports, checked literally, not just by convention.

---

## 3. NPCI's UAP and where this build already lines up

NPCI's UAP (Unified/Agentic Payments layer for UPI) is the Indian analogue
of the protocol race AP2, ACP, and x402 are running elsewhere: it layers
agent *registration and authorization* on top of existing UPI rails rather
than replacing them — an agent identity gets registered and authorized to
act on a user's behalf, and the underlying UPI payment mechanics are
unchanged. That's a materially different shape from AP2's mandate-signing
model, but the *merchant-side obligation* rhymes closely with what this
build already does: a merchant needs to expose a machine-readable surface
that a registered, authorized agent identity can discover and transact
against, and needs to verify that whatever identity is presenting itself is
actually the one it claims to be before honoring a request. Concretely,
`surface/mandate.py`'s buyer-identity verification (an Ed25519 public key
the buyer controls, checked against every request) and
`surface/mcp_server.py`'s capability manifest (a structured description of
what's purchasable and under what policy, machine-readable rather than
prose a buyer agent would have to parse) are the two pieces of this build
that would extend most directly to a UAP world: the manifest becomes what
gets registered with UAP's agent registry, and the signature-verification
posture — never trust a caller's claimed identity without independently
checking it — is the same posture UAP's registration/authorization layer
would require of any merchant-side integration, protocol details aside.
Full UAP integration is out of scope here (Tier 4, future work) — this is
the specific reason the AP2 work done for this build is not a dead end if
the Indian rail is the one that ships first.
