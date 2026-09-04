"""
Canonicalization agent -- Tier 1.

model_compat is the one genuinely free-text field pipeline/extract.py
produces: accessory_type, connector_type, and material are already
enum-constrained by ProductAttributes itself (Pydantic forces the LLM's
structured output into one of the defined members), so there is nothing
left to canonicalize there. model_compat has no such constraint -- it is
canonical phone-model text, and each SKU's extraction call has no
visibility into how OTHER SKUs phrased the same real device. The same
device can legitimately come back as "iphone_5s" from one row and
"apple_iphone_5s" from another even when both extractions did their best.

Local embedding search (ChromaDB's default all-MiniLM-L6-v2, ONNX, runs
entirely on-device, zero LLM quota) finds CANDIDATE near-duplicate pairs
within CANDIDATE_DISTANCE -- but distance alone never decides a merge,
past true string identity (case/whitespace only). Embedding distance
cannot reliably separate "same device, different phrasing" from "similarly
named but different device": "iphone_6" vs "iphone_6s" -- genuinely
different phones -- measures distance 0.12, CLOSER than several pairs that
are only a formatting difference apart. An even tighter fixed threshold
still isn't safe: "xiaomi_redmi_mi4" vs "xiaomi_redmi_mi4i" (a single
suffix character) measures near-zero, yet the LLM confirmed elsewhere in
the same run that plain "mi4" and "mi4i" are different Xiaomi models --
that pair auto-merging under an earlier version of this threshold
transitively chained two DIFFERENT phones into one cluster, caught only
because it directly contradicted another pair's explicit LLM verdict (see
_detect_contradictions). So every candidate pair gets a real LLM
adjudication call: same real device or different, structured, disk-cached
per pair so a re-run costs zero quota. This project never silently guesses
about anything that could publish a wrong compatibility claim -- a pair
the LLM itself can't confidently resolve is left unmerged, and clustering
NEVER merges across a pair the LLM confidently called different, even if
some other chain of merges would have connected them anyway (transitivity
does not override a direct contradictory verdict).

Values with no close neighbor at all stay singleton clusters (canonical
form = themselves). Nothing here ever quarantines a SKU directly --
canonicalize_model_compat_values() returns unmapped_low_confidence for any
value the process couldn't confidently place, and it is the CALLER's
decision whether that's grounds to drop the claim (mirroring
pipeline/quarantine.py's "the loss is visible, not silent" principle from
eval/build_ground_truth.py).
"""

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import chromadb
from pydantic import BaseModel
from pydantic import Field as PydanticField

from pipeline.llm_clients import get_chat_model_with_fallback

ROOT = Path(__file__).resolve().parent.parent
ADJUDICATION_CACHE_DIR = ROOT / "data" / "canonical_adjudication_cache"

CANDIDATE_DISTANCE = 0.6  # below this: a real LLM adjudication call; at or above: not even a candidate, no call spent


@dataclass
class CanonicalizationResult:
    canonical: dict[str, str] = field(default_factory=dict)  # raw value -> canonical value
    clusters: list[list[str]] = field(default_factory=list)  # each cluster, for auditability
    llm_adjudications: list[dict] = field(default_factory=list)  # every LLM call made, same/different + reason
    unmapped_low_confidence: list[str] = field(default_factory=list)  # values the LLM adjudicated as genuinely uncertain about a neighbor -- caller decides whether to trust them alone
    contradictions_prevented: list[dict] = field(default_factory=list)  # merges that would have chained two values across a confirmed-different verdict; blocked, not silently allowed


class _AdjudicationResponse(BaseModel):
    same_device: bool
    confident: bool = PydanticField(description="False if this is genuinely a coin flip even for you -- don't force a guess")
    reason: str = ""


def _adjudication_cache_key(a: str, b: str, prompt_version: str) -> str:
    pair = "|".join(sorted([a, b]))
    return hashlib.sha256(f"{pair}|{prompt_version}".encode()).hexdigest()


def _cache_get(key: str) -> dict | None:
    path = ADJUDICATION_CACHE_DIR / f"{key}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _cache_put(key: str, value: dict) -> None:
    ADJUDICATION_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (ADJUDICATION_CACHE_DIR / f"{key}.json").write_text(json.dumps(value), encoding="utf-8")


PROMPT_VERSION = "v1"


def adjudicate_pair(a: str, b: str, use_cache: bool = True) -> dict:
    """Asks the LLM whether two canonical-ish phone-model tokens name the
    SAME real device or DIFFERENT ones. Disk-cached per (unordered) pair."""
    key = _adjudication_cache_key(a, b, PROMPT_VERSION)
    cached = _cache_get(key) if use_cache else None
    if cached is not None:
        return cached

    model = get_chat_model_with_fallback("canonicalizer", output_schema=_AdjudicationResponse)
    prompt = (
        "Two phone-model identifiers were extracted from two different product listings in the "
        "same catalog. Do they name the SAME real phone model, or two DIFFERENT models?\n\n"
        f"A: {a}\nB: {b}\n\n"
        "Judge only on whether they refer to the same physical device (naming/formatting "
        "differences like underscores, an 'apple_' prefix, or spelling don't make them "
        "different). A different model NUMBER, generation, or variant (e.g. a 'Plus'/'Prime'/"
        "'Dual'/'S' suffix that denotes an actually different SKU) makes them different devices. "
        "If you are not genuinely confident either way, set confident=false rather than guessing."
    )
    response = model.invoke(
        prompt, config={"run_name": f"canonical:adjudicate:{a}:{b}", "tags": ["canonical", "adjudicate"]}
    )
    result = {"a": a, "b": b, "same_device": response.same_device, "confident": response.confident, "reason": response.reason}
    if use_cache:
        _cache_put(key, result)
    return result


class _UnionFind:
    def __init__(self, items: list[str]):
        self.parent = {item: item for item in items}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb

    def members_of(self, x: str) -> list[str]:
        root = self.find(x)
        return [item for item in self.parent if self.find(item) == root]

    def groups(self) -> list[list[str]]:
        by_root: dict[str, list[str]] = {}
        for item in self.parent:
            by_root.setdefault(self.find(item), []).append(item)
        return list(by_root.values())


def _looks_canonical(value: str) -> bool:
    """Heuristic for picking a cluster's representative: snake_case,
    lowercase, no stray punctuation -- what pipeline/extract.py's prompt
    actually asks for. Prefers a value that already matches this shape
    when choosing which raw string becomes the cluster's canonical form."""
    return bool(re.fullmatch(r"[a-z0-9]+(_[a-z0-9]+)*", value))


def _pick_representative(cluster: list[str], counts: dict[str, int]) -> str:
    canonical_looking = [v for v in cluster if _looks_canonical(v)]
    pool = canonical_looking or cluster
    return max(sorted(pool), key=lambda v: counts.get(v, 0))


def canonicalize_model_compat_values(raw_values: list[str], use_cache: bool = True) -> CanonicalizationResult:
    unique_values = sorted(set(raw_values))
    counts = {v: raw_values.count(v) for v in unique_values}
    result = CanonicalizationResult()

    if not unique_values:
        return result

    # A fresh client AND a uniquely-named collection each call -- an
    # EphemeralClient() without an explicit path can still resolve to
    # shared underlying storage within the same process, so a fixed
    # collection name let a PRIOR call's values leak into a later call's
    # nearest-neighbor results (caught via a real KeyError in testing, not
    # assumed). Each invocation must be fully isolated from any other.
    client = chromadb.EphemeralClient()
    collection = client.get_or_create_collection(f"model_compat_values_{uuid.uuid4().hex}")
    collection.add(ids=unique_values, documents=unique_values)

    uf = _UnionFind(unique_values)
    checked_pairs: set[frozenset] = set()
    confirmed_same: list[tuple[str, str]] = []
    confirmed_different: set[frozenset] = set()

    # Stage 1: resolve every candidate pair to same / different / unsure --
    # no merging yet. Exact string identity (case/whitespace only) is the
    # one case safe enough to skip the LLM call entirely.
    n_neighbors = min(5, len(unique_values))
    for value in unique_values:
        neighbors = collection.query(query_texts=[value], n_results=n_neighbors + 1)
        for neighbor_id, distance in zip(neighbors["ids"][0], neighbors["distances"][0], strict=True):
            if neighbor_id == value or distance >= CANDIDATE_DISTANCE:
                continue
            pair_key = frozenset({value, neighbor_id})
            if pair_key in checked_pairs:
                continue
            checked_pairs.add(pair_key)

            if value.strip().lower() == neighbor_id.strip().lower():
                confirmed_same.append((value, neighbor_id))
                continue

            adjudication = adjudicate_pair(value, neighbor_id, use_cache=use_cache)
            result.llm_adjudications.append(adjudication)
            if adjudication["confident"] and adjudication["same_device"]:
                confirmed_same.append((value, neighbor_id))
            elif adjudication["confident"]:
                confirmed_different.add(pair_key)
            else:
                result.unmapped_low_confidence.extend([value, neighbor_id])

    # Stage 2: apply "same" merges one at a time, but never merge two
    # clusters that would put a confirmed-different pair together --
    # transitivity (A same B, B same C) must not override a DIRECT
    # different verdict on A vs C, even though nothing here ever compares
    # A and C to each other. Caught for real: an earlier version of this
    # function merged via distance alone and produced exactly this
    # contradiction (see module docstring).
    for a, b in confirmed_same:
        group_a, group_b = uf.members_of(a), uf.members_of(b)
        blocking_pair = next(
            (frozenset({x, y}) for x in group_a for y in group_b if frozenset({x, y}) in confirmed_different),
            None,
        )
        if blocking_pair is not None:
            result.contradictions_prevented.append({"blocked_merge": [a, b], "because_confirmed_different": sorted(blocking_pair)})
            continue
        uf.union(a, b)

    for cluster in uf.groups():
        representative = _pick_representative(cluster, counts)
        result.clusters.append(sorted(cluster))
        for raw_value in cluster:
            result.canonical[raw_value] = representative

    result.unmapped_low_confidence = sorted(set(result.unmapped_low_confidence))
    return result
