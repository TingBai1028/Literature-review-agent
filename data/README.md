# Data

Hackathon rule: use open data you can use legally, keep samples small, add download scripts, and avoid sensitive or restricted data.

## Sources

| Source | What we use | Licence / terms |
| --- | --- | --- |
| OpenAlex | Paper metadata and abstracts | CC0 (check https://openalex.org) |
| Semantic Scholar | Metadata, citation links | TODO: check API terms |
| arXiv | Preprints and full-text PDFs | TODO: check per-paper licence |

## In this folder

- `sample/`: TODO: a few small JSON files of papers for tests and the demo
- `raw/`, `pdfs/`, `cache/`: downloaded data; git-ignored. Recreate with `python scripts/download_sample_data.py`.
