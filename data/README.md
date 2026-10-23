# Data

Hackathon rule: use open data you can use legally, keep samples small, add download scripts, and avoid sensitive or restricted data.

## Sources

| Source | What we use | Licence / terms |
| --- | --- | --- |
| OpenAlex | Paper metadata and abstracts | CC0 (check https://openalex.org) |
| Semantic Scholar | Metadata, citation links | TODO: check API terms |
| arXiv | Preprints and full-text PDFs | TODO: check per-paper licence |

## In this folder

- `sample/`: real OpenAlex papers (CC0), about 60 per topic, used by sample mode (`SAMPLE_MODE=true`) and the tests. The Retriever picks the file whose name shares the most words with the question. Add a topic with
  `python scripts/download_sample_data.py "your topic" --limit 60 --year-from 2021 --out data/sample --name your_topic_words`.
- `raw/`, `pdfs/`, `cache/`: downloaded data; git-ignored. Recreate with `python scripts/download_sample_data.py`.
