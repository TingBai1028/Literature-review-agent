"""Stable, deterministic, content-addressable IDs (spec: docs/stable-ids.md).

Python port of the Meterless World Model reference, engines/world-model/reference/src/stableIds.ts
(https://github.com/Meterless/Meterless, Apache-2.0). Same input, same ID, on every machine and
every re-run; tests/test_world_model_conformance.py checks the IDs match the TypeScript reference.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

_COMBINING_MARKS = re.compile("[̀-ͯ]")
_ZERO_WIDTH = re.compile("[​-‍﻿]")
_WHITESPACE = re.compile(r"\s+")


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    """Deterministic JSON: sorted keys, no spaces. Optional fields are omitted from records rather
    than set to None, which mirrors the reference dropping `undefined` members."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def normalize_name(name: str) -> str:
    """NFKD -> strip combining marks -> strip zero-width chars -> lowercase -> collapse whitespace -> trim.
    Never abbreviates or drops word characters: "Acme Corp" and "Acme Corporation" stay different."""
    text = unicodedata.normalize("NFKD", name)
    text = _ZERO_WIDTH.sub("", _COMBINING_MARKS.sub("", text))
    return _WHITESPACE.sub(" ", text.lower()).strip()


def external_id(type_: str, system: str, id_: str) -> str:
    """Externally keyed entity or context: the literal grammar `type:system:externalId`."""
    return f"{type_}:{system}:{id_}"


def entity_id_from_name(type_: str, name: str) -> str:
    """Name-keyed entity: ent_<first 16 hex of sha256(f"{type}:{normalize_name(name)}")>."""
    return "ent_" + sha256_hex(f"{type_}:{normalize_name(name)}")[:16]


def context_id_from_attrs(type_: str, attrs: dict[str, Any], parent: str | None = None) -> str:
    return "ctx_" + sha256_hex(f"{type_}:{canonical_json(attrs)}:{parent or ''}")[:16]


def relationship_id(from_id: str, type_: str, to_id: str, context: str | None = None, valid_from: str | None = None) -> str:
    """Re-adding the same edge is a no-op because the ID is derived from its content."""
    return "rel_" + sha256_hex(f"{from_id}|{type_}|{to_id}|{context or ''}|{valid_from or ''}")[:16]


def fact_id(about: str, predicate: str, value: Any, asserted_at: str, source_kind: str, source_url: str | None = None) -> str:
    return "fact_" + sha256_hex(
        f"{about}|{predicate}|{canonical_json(value)}|{asserted_at}|{source_kind}|{source_url or ''}"
    )[:16]


def iso(dt: datetime | None = None) -> str:
    """Timestamps in the reference's format (JavaScript toISOString: millisecond precision, `Z`).
    The store compares timestamps as strings, so every writer must use this one format."""
    dt = (dt or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
