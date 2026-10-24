"""Check the Clusterer's similarity threshold on real papers, before changing it in config.py.

    python scripts/check_threshold.py                      # every topic in data/sample/
    python scripts/check_threshold.py data/raw/*.json      # your own downloads (scripts/download_sample_data.py)
    python scripts/check_threshold.py --papers 30          # as many papers as a Normal run keeps

For each topic and threshold it prints the number of clusters (groups of >= min_cluster_size), their
sizes, how many papers fit no group, and the largest cluster's share. A good threshold gives several
clusters, a largest share under the grader's 40% limit, and few unclustered papers.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from litagent.agents.clusterer import average_linkage, center, cosine_similarity_matrix, embed  # noqa: E402
from litagent.config import EMBEDDING_MODEL, Settings  # noqa: E402
from litagent.schemas import Paper  # noqa: E402

THRESHOLDS = [round(t, 2) for t in np.arange(-0.05, 0.31, 0.05)]  # mean-centered cosine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", default=sorted(glob.glob("data/sample/*.json")))
    parser.add_argument("--papers", type=int, default=60, help="Papers per topic (Normal keeps 30, Medium 60)")
    args = parser.parse_args()
    settings = Settings()
    print(f"Embedding model: {EMBEDDING_MODEL}; current threshold {settings.cluster_similarity_threshold}; "
          f"min cluster size {settings.min_cluster_size}\n")

    for file in args.files:
        papers = [p for p in (Paper.model_validate(d) for d in json.loads(Path(file).read_text())) if p.abstract][:args.papers]
        start = time.monotonic()
        sim = cosine_similarity_matrix(center(embed([f"{p.title}. {p.abstract}" for p in papers])))
        print(f"== {Path(file).stem}: {len(papers)} papers, embedded in {time.monotonic() - start:.1f} s ==")
        print(f"{'threshold':>9}  {'clusters':>8}  {'largest':>7}  {'unclustered':>11}  sizes")
        for t in THRESHOLDS:
            groups = average_linkage(sim, t)
            sizes = sorted((len(g) for g in groups if len(g) >= settings.min_cluster_size), reverse=True)
            unclustered = len(papers) - sum(sizes)
            largest = max(sizes, default=0) / len(papers)
            flag = "  <- over 40%" if largest > 0.4 else ""
            print(f"{t:>9.2f}  {len(sizes):>8}  {largest:>6.0%}  {unclustered:>11}  {sizes[:12]}{flag}")
        print()


if __name__ == "__main__":
    main()
