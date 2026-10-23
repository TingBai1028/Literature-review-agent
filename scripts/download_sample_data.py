"""Download a small sample of papers from OpenAlex for testing and the demo.

    python scripts/download_sample_data.py "your topic" --limit 30                       # -> data/raw/ (git-ignored)
    python scripts/download_sample_data.py "your topic" --limit 60 --out data/sample \
        --name graph_neural_networks_drug_discovery                                      # -> committed sample-mode data
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from litagent.schemas import SearchCriteria  # noqa: E402
from litagent.tools.openalex import search_openalex  # noqa: E402

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("topic")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--year-from", type=int, default=None)
    parser.add_argument("--out", default=str(OUT_DIR), help="Output folder (data/sample/ is what sample mode reads)")
    parser.add_argument("--name", default=None, help="File name without .json; sample mode matches question words against it")
    args = parser.parse_args()

    papers = search_openalex(args.topic, SearchCriteria(topic=args.topic, year_from=args.year_from), limit=args.limit)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{args.name or args.topic.replace(' ', '_')[:50]}.json"
    out.write_text(json.dumps([p.model_dump(mode="json") for p in papers], indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {len(papers)} papers to {out}")


if __name__ == "__main__":
    main()
