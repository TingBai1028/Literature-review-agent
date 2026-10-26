# Pre-existing components

Required in the submission: declare anything built before 22 October 2026.

| Component | What it is | Where it's used | Built by |
| --- | --- | --- | --- |
| Meterless World Model spec, TypeScript reference implementation and conformance suite ([Meterless/Meterless `engines/world-model`](https://github.com/Meterless/Meterless/tree/main/engines/world-model), Apache-2.0) | The design we implemented; our Python code in `litagent/integrations/world_model/` is ported from the reference, and our conformance tests port its suite. Licence copy: `litagent/integrations/world_model/LICENSE-meterless-world-model` | `litagent/integrations/world_model/`, `tests/test_world_model_conformance.py` | Meterless |
| Zetaris getting-started guides ([zetaris/getting-started](https://github.com/zetaris/getting-started)) | Connection settings and the REST SQL call our client uses | `litagent/integrations/zetaris.py`, `docs/setup-zetaris.md` | Zetaris |
| [all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2), Apache-2.0 | Pretrained semantic embeddings; pinned revision, prepared once and loaded locally on CPU | `litagent/integrations/embeddings.py`, Clusterer | Sentence Transformers |
| [SemCSE cosine](https://huggingface.co/CLAUSE-Bielefeld/SemCSE_cosine), MIT | Scientific-content encoder; documented CLS pooling; pinned revision, CPU-only offline loading | Default Clusterer representation | Marc Brinner, Sina Zarrieß / Bielefeld University |
| SGHA novelty and corpus-coverage classifier prompt (Gharat and Komiyama 2026, [arXiv 2608.17501](https://arxiv.org/abs/2608.17501), appendix A.3) | The gap labels (`trivial`, `known_open`, `known_solved`, `novel`) and their wording are adapted from the paper's prompt; no code from their repository is used | `prompts/gap_grader.md`, Gap finder stage 4 | Gharat and Komiyama |
| [Source Serif 4](https://github.com/adobe-fonts/source-serif), SIL Open Font License 1.1, bundled through `@fontsource-variable/source-serif-4` | The interface's typeface | `frontend/src/main.tsx` | Adobe (Frank Grießhammer) |

Open-source libraries listed in `requirements.txt` and `frontend/package.json` are third-party dependencies.

Everything else in this repository was built during the hackathon (22–27 October 2026).
