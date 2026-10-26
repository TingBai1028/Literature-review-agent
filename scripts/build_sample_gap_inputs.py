"""Prepare the Gap finder's offline inputs for sample mode (run once after adding a sample topic).

    python scripts/build_sample_gap_inputs.py

Sample mode has no network and no embedding model, but the Gap finder's candidate generator needs
each paper's reference list and the paper-paper similarity matrix. This script:

1. fetches OpenAlex `referenced_works` for every paper in data/sample/*.json and stores it as `references`;
2. embeds the papers with the pinned clustering model (scripts/setup_embeddings.py first) and writes the
   similarity matrix the Clusterer would compute to data/sample/similarity/<topic>.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from litagent.agents.clusterer import _text_for  # noqa: E402
from litagent.config import EMBEDDING_PROFILES, Settings  # noqa: E402
from litagent.integrations.embeddings import embed_documents  # noqa: E402
from litagent.schemas import Paper  # noqa: E402
from litagent.similarity import paper_similarity  # noqa: E402
from litagent.tools.openalex import BASE_URL, _get_with_retry  # noqa: E402

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample"
BATCH = 50  # OpenAlex accepts up to 50 ids in one OR filter


def fetch_references(ids: list[str]) -> dict[str, list[str] | None]:
    found = {}
    for start in range(0, len(ids), BATCH):
        batch = ids[start:start + BATCH]
        data = _get_with_retry(BASE_URL, {"filter": "openalex:" + "|".join(batch), "per-page": BATCH,
                                          "select": "id,referenced_works"})
        for work in data.get("results", []):
            refs = work.get("referenced_works") or []
            found[work["id"].rsplit("/", 1)[-1]] = [r.rsplit("/", 1)[-1] for r in refs] or None
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-references", action="store_true", help="Only recompute the similarity matrices")
    args = parser.parse_args()
    settings = Settings()
    profile = EMBEDDING_PROFILES[settings.embedding_profile]
    (SAMPLE_DIR / "similarity").mkdir(exist_ok=True)
    for path in sorted(SAMPLE_DIR.glob("*.json")):
        records = json.loads(path.read_text(encoding="utf-8"))
        if not args.skip_references:
            refs = fetch_references([r["id"] for r in records if r["source"] == "openalex"])
            for r in records:
                r["references"] = refs.get(r["id"])
            path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"{path.name}: reference lists for {sum(r['references'] is not None for r in records)} of {len(records)} papers")
        papers = [Paper.model_validate(r) for r in records]
        vectors = embed_documents([_text_for(p, False) for p in papers], settings)
        similarity = paper_similarity(papers, vectors, settings).combined
        out = SAMPLE_DIR / "similarity" / path.name
        out.write_text(json.dumps({
            "embedding_profile": settings.embedding_profile, "model": profile["model"], "revision": profile["revision"],
            "paper_ids": [p.id for p in papers], "similarity": [[round(float(v), 4) for v in row] for row in similarity],
        }), encoding="utf-8")
        print(f"{out.relative_to(SAMPLE_DIR.parent.parent)}: {len(papers)}x{len(papers)} similarity")


if __name__ == "__main__":
    main()
