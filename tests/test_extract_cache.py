import importlib

from pipeline import extract_cache


def test_cache_key_changes_with_any_input(monkeypatch, tmp_path):
    monkeypatch.setattr(extract_cache, "CACHE_DIR", tmp_path)
    base = extract_cache.cache_key("SKU-1", "a description", "v1", "gemini-2.5-flash")
    assert base != extract_cache.cache_key("SKU-2", "a description", "v1", "gemini-2.5-flash")
    assert base != extract_cache.cache_key("SKU-1", "a different description", "v1", "gemini-2.5-flash")
    assert base != extract_cache.cache_key("SKU-1", "a description", "v2", "gemini-2.5-flash")
    assert base != extract_cache.cache_key("SKU-1", "a description", "v1", "openai/gpt-oss-120b")


def test_cache_key_is_stable_for_identical_input():
    a = extract_cache.cache_key("SKU-1", "desc", "v1", "model")
    b = extract_cache.cache_key("SKU-1", "desc", "v1", "model")
    assert a == b


def test_get_returns_none_when_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(extract_cache, "CACHE_DIR", tmp_path)
    assert extract_cache.get("nonexistent-key") is None


def test_put_then_get_round_trips(monkeypatch, tmp_path):
    monkeypatch.setattr(extract_cache, "CACHE_DIR", tmp_path)
    key = extract_cache.cache_key("SKU-1", "desc", "v1", "model")
    value = {"attributes": {"accessory_type": {"value": "cable", "confidence": 0.9}}}
    extract_cache.put(key, value)
    assert extract_cache.get(key) == value


def test_invalidate_removes_entry(monkeypatch, tmp_path):
    monkeypatch.setattr(extract_cache, "CACHE_DIR", tmp_path)
    key = extract_cache.cache_key("SKU-1", "desc", "v1", "model")
    extract_cache.put(key, {"x": 1})
    extract_cache.invalidate(key)
    assert extract_cache.get(key) is None


def test_invalidate_missing_key_does_not_raise(monkeypatch, tmp_path):
    monkeypatch.setattr(extract_cache, "CACHE_DIR", tmp_path)
    extract_cache.invalidate("never-existed")  # should not raise


def test_stats_counts_entries(monkeypatch, tmp_path):
    monkeypatch.setattr(extract_cache, "CACHE_DIR", tmp_path)
    assert extract_cache.stats() == {"entries": 0}
    extract_cache.put(extract_cache.cache_key("SKU-1", "d", "v1", "m"), {"x": 1})
    extract_cache.put(extract_cache.cache_key("SKU-2", "d", "v1", "m"), {"x": 2})
    assert extract_cache.stats() == {"entries": 2}


def test_stats_on_nonexistent_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(extract_cache, "CACHE_DIR", tmp_path / "does-not-exist-yet")
    assert extract_cache.stats() == {"entries": 0}


def test_module_reloads_cleanly():
    # sanity check the module itself has no import-time side effects that
    # would break re-importing (e.g. in a test runner that reloads modules)
    importlib.reload(extract_cache)
