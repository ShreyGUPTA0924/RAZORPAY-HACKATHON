"""Tier 1. Not yet implemented.

Canonicalization agent: messy raw values (e.g. "USB C" / "Type-C" / "usb-c")
-> the canonical enums defined in pipeline.schema, via embedding clustering
(ChromaDB) + LLM adjudication on cluster boundaries.
"""
