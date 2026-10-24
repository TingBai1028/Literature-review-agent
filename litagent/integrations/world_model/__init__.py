"""Meterless World Model, implemented in Python from the Meterless spec (engines/world-model/AGENTS.md)
and its TypeScript reference implementation (https://github.com/Meterless/Meterless, Apache-2.0).

Conformance: tests/test_world_model_conformance.py ports the spec's conformance suite
(engines/world-model/conformance/runner.ts) check for check. litagent's own use of it, mapping
papers, clusters, connections and gaps onto entities and relationships, lives in
litagent/integrations/meterless.py.
"""

from litagent.integrations.world_model.model import WorldModel, WorldModelError
from litagent.integrations.world_model.resolve import decide, jaccard, levenshtein, name_similarity
from litagent.integrations.world_model.stable_ids import (
    canonical_json, entity_id_from_name, external_id, iso, normalize_name, sha256_hex,
)

__all__ = [
    "WorldModel", "WorldModelError", "decide", "jaccard", "levenshtein", "name_similarity",
    "canonical_json", "entity_id_from_name", "external_id", "iso", "normalize_name", "sha256_hex",
]
