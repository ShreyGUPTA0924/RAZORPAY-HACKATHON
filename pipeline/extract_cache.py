"""
Persistent disk cache for pipeline/extract.py results.

Extraction is never recomputed once cached: keyed on
hash(sku_id + description + prompt_version + model), so a change to any of
those (a different SKU, an edited description, a prompt rewrite, or a model
swap) correctly misses the cache instead of serving a stale answer. Re-runs
after the first hit cost zero quota -- this is what makes demo rehearsal
possible without burning the free tier every time.

One JSON file per cache key under data/extraction_cache/. Deliberately not a
single combined file: this stays correct under concurrent/interrupted runs
(each SKU's cache write is independent; a crash mid-batch doesn't corrupt
already-cached entries), and a stale entry can be deleted individually
without touching the rest.

Only successful extractions are cached. An error is not an answer -- it
should be retried next run, not permanently frozen as "the result".
"""

import hashlib
import json
from pathlib import Path
from typing import Any

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "extraction_cache"


def cache_key(sku_id: str, description: str, prompt_version: str, model: str) -> str:
    raw = f"{sku_id}|{description}|{prompt_version}|{model}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def get(key: str) -> dict[str, Any] | None:
    path = _path(key)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def put(key: str, value: dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _path(key).write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def invalidate(key: str) -> None:
    _path(key).unlink(missing_ok=True)


def stats() -> dict[str, int]:
    if not CACHE_DIR.exists():
        return {"entries": 0}
    return {"entries": sum(1 for _ in CACHE_DIR.glob("*.json"))}
