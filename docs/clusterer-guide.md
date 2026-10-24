# Clusterer: how it works, what was decided, what's open

The Clusterer is step 3 of the pipeline. It takes the papers the Retriever found (30–150, all on one topic) and groups them into labelled research ideas: the clusters on the paper map. The Connection finder and Gap finder work inside these clusters, so their quality depends on it.

- **Code:** `litagent/agents/clusterer.py`
- **Prompt:** `prompts/cluster_labeler.md`
- **Short spec:** `docs/agents/clusterer.md`
- **Status (24 Oct):** working. Tested with mocked embeddings and LLM, plus a live check on 30 real papers with Nemotron 3 Ultra.

---

## 1. What happens in a run

```
papers ─► 1. text ─► 2. embed ─► 3. center ─► 4. group ─► 5. label ─► clusters + unclustered
                                                                          │
                                       grading agent ◄────────────────────┘
                                       pass (≥ 7/9) → Connection finder
                                       fail → one redo with the grader's fix, then continue with a warning
```

1. **Text.** Each paper becomes `title + ". " + abstract`, capped at 2,000 characters (`EMBEDDING_MAX_CHARS`). Papers without an abstract never get here: the Retriever drops them.
2. **Embed.** A local model turns each text into a 384-number vector (`embed()`). Model: `BAAI/bge-small-en-v1.5`, run by `fastembed` (ONNX, no PyTorch, no GPU).
3. **Center.** The vectors are normalized, then the run's average vector is subtracted (`center()`). Section 3 explains why.
4. **Group.** Average-linkage clustering (`average_linkage()`): start with every paper on its own, repeatedly merge the two groups with the highest *average* similarity, and stop when that average drops below the threshold (0.05). Groups smaller than 2 papers are left out and recorded as **unclustered**.
5. **Label.** **One** LLM call (Nemotron 3 Ultra via Nightshift) labels every group. The model sees each paper's title and the first 300 characters of its abstract, and returns, per group:
   - `label`: 3–8 words
   - `rationale`: one sentence
   - `coherent`: true or false
6. **Grade.** The grading agent checks the clusters (section 5).
7. **Record.** The orchestrator writes the clusters (`paper -member-of-> cluster`) and the unclustered papers (`paper -unclustered-in-> search`) to the Meterless World Model. It also adds `unclustered_paper_ids` to the run result and `unclustered` to the paper map.

**Sample mode** (`SAMPLE_MODE=true`) skips all of this. It splits the papers round-robin into 3 placeholder clusters labelled "Sample theme N", with no embeddings and no LLM call.

---

## 2. Decisions

### Made by you

| Decision | Choice | Rejected options |
|---|---|---|
| Embeddings | `fastembed` + `bge-small` (local) | SPECTER via PyTorch (+1–1.5 GB image, +1 h); Nemotron grouping papers directly (drops the team's similarity + threshold design, different results each run) |
| Grouping | Average linkage | Connected components (the original `group_by_threshold`), which chains A~B~C into one giant cluster |
| Papers that fit no group | Set aside as "unclustered", kept for the Gap finder | Drop them; keep them as one-paper clusters, which fail the grader's single-paper rule |

### Made by Claude, without asking (please review)

| # | Decision | Why | Easy to change? |
|---|---|---|---|
| 1 | **Mean-centering the embeddings** | Without it, no threshold worked (section 3) | Yes: remove `center()` in `cluster()` |
| 2 | **Threshold 0.05 instead of the team's 0.7** | 0.7 has no meaning after centering; 0.05 was best on 3 topics. ⚠️ `ARCHITECTURE.md` still says "cosine ≥ 0.7" and needs updating | `cluster_similarity_threshold` in `config.py` |
| 3 | Text to embed is title + abstract (in the plan, but not asked) | Extracting key claims first would cost an LLM call per paper | Yes |
| 4 | Groups the labeller calls incoherent are dropped, and their papers become unclustered | Don't show a cluster that has no shared idea | Yes: keep them labelled "Mixed" instead |
| 5 | A redo moves the threshold by **matching keywords** in the grader's fix ("too broad / split" → +0.05; "no clusters / too many / merge / fragmented" → −0.05) | The grader's fix is free text | Better: have the grader return a structured instruction (grading-agent step) |
| 6 | Minimum cluster size 2 | Pairs are still useful to the Gap finder | `min_cluster_size` |
| 7 | High and Ultra also use title + abstract | Full text isn't implemented (it would need the Markovian engine) | When full text exists |
| 8 | One LLM call labels every group | Fewer calls and tokens, faster | Yes |
| 9 | The labeller sees the title + first 300 abstract characters | Keeps the call around 10k tokens at 30 papers | `ABSTRACT_CHARS_FOR_LABELS` |
| 10 | A group the labeller skips gets its first paper's title as the label | Never lose papers silently | Yes |
| 11 | Cluster IDs are renumbered C1…Cn, largest first, after drops | Stable, readable IDs | — |
| 12 | `group_by_threshold` removed; commented-out PyTorch libraries removed from `requirements.txt` | Replaced by average linkage and `fastembed` | — |

---

## 3. Why mean-centering and 0.05 (the evidence)

All papers in a run are about the same topic, so their embeddings share one big "topic direction". Raw similarity scores sit in a narrow band: papers on the same topic averaged 0.84, and even papers on *different* topics averaged 0.65. Within one topic, a fixed threshold can only produce one giant cluster or lots of leftovers.

**Raw cosine, best threshold per topic (30 real papers each):**

| Topic | Best threshold | Clusters | Largest | Unclustered |
|---|---|---|---|---|
| GNNs in drug discovery | 0.90 | 3 | 27% | **16 of 30** |
| LLMs and low-resource languages | 0.86 | 8 | 13% | 7 of 30 |
| Protein structure prediction | 0.90 | 4 | 33% | **14 of 30** |

Below these thresholds, one cluster held 47–100% of the papers, which fails the grader's 40% rule.

**Mean-centered cosine at 0.05 (same papers, plus the 60-paper Medium case):**

| Topic | 30 papers | 60 papers |
|---|---|---|
| GNNs in drug discovery | 6 clusters, largest 30%, 1 unclustered | 8 clusters, largest 24%, 0 unclustered |
| LLMs and low-resource languages | 8 clusters, largest 23%, 0 unclustered | 9 clusters, largest 16%, 0 unclustered |
| Protein structure prediction | 6 clusters, largest 20%, 0 unclustered | 9 clusters, largest 23%, 0 unclustered |

Nearby values: 0.00 gave fewer, bigger clusters (largest up to 40%); 0.10 gave more, smaller ones (7–14 clusters, up to 4 unclustered).

**Re-check any time** (on the samples, or on your own downloads):

```bash
.venv/bin/python scripts/check_threshold.py --papers 30
.venv/bin/python scripts/check_threshold.py data/raw/*.json --papers 60
```

The 3 calibration topics are all ML-flavoured; a very different field may want a slightly different value.

---

## 4. Why a local model (and not Nightshift)

Nightshift's API returns `501: POST /v1/embeddings is not served in the web build` (tested 24 Oct with `nvidia/nemotron-3-embed-1b`). Calling NVIDIA's API directly isn't allowed: the rules keep the NVIDIA key inside Nightshift. So embeddings run locally:

- **Size:** about 130 MB. The Docker image downloads it **at build time** (`ARG EMBEDDING_MODEL` in the `Dockerfile`), and a test checks it matches `config.EMBEDDING_MODEL`.
- **Offline:** checked with `docker run --network none …`; embeddings work with no network.
- **Speed:** about 5–7 s for 30 papers, 20–40 s for 120 on a MacBook. It's slower while the Zetaris containers are busy, because they run under emulation.
- **Locally,** `fastembed` caches the model in the system temp folder. Set `EMBEDDING_CACHE_DIR` to choose another place.

If a Nightshift build ever serves embeddings, only `embed()` needs to change. It's worth asking the Help Meterless channel: it would mean one more NVIDIA model in use.

---

## 5. Grading and redo

After clustering, `_graded_stage` in `litagent/orchestrator.py` runs the grading agent:

1. **Rule-based size check first** (`check_cluster_sizes` in `grader.py`):
   - No clusters → fix "No clusters were produced." (the redo lowers the threshold)
   - Largest cluster > 40% of papers → "One cluster is too broad; split the largest cluster." (the redo raises the threshold)
   - More than 50% single-paper clusters → can't happen now, since singletons are set aside
2. **The LLM grader** (`prompts/grader.md`) scores accuracy, appropriateness and actionability, 0–3 each. It passes at 7/9 (`grade_pass_mark`).
3. **On a fail:** one redo (`max_redo_per_stage = 1`) with the grader's fix. The fix reaches the labeller (`fix_from_grader`) and may move the threshold. If it still fails, the run continues with a warning in `RunResult.warnings`.
4. **Every grade** is stored as a fact in the World Model (the newest wins, history kept) and logged in the trace.

**Known issue:** in the live check, the LLM grader gave 6/9 with **five** fixes in one string ("merge C1 and C2; split C3; reassign …"). The grader is meant to return *one* concrete fix. That's the next step (the grading agent, prompt 4).

---

## 6. Live check (24 Oct)

30 real papers on GNNs in drug discovery, run through Nemotron 3 Ultra:

- **Grouping:** 6 groups. The labeller called 1 incoherent, so **5 clusters**, with **3 papers unclustered**.
- **Clusters:**
  - Graph neural networks for molecular property prediction (9)
  - Survey and bibliometric reviews of GNNs in drug discovery (7)
  - GNNs combined with RL, docking, and quantum methods (6)
  - GNNs for pharmacokinetics and disease-specific drug discovery (3)
  - Explainable GNNs for drug mechanism and resistance (2)
- **Cost:** 27 s in total, 7 s of it embedding. 2 LLM calls (label + grade), about 13.3k prompt and 0.7k completion tokens.

A full real run through the Clusterer wasn't possible that day: OpenAlex's keyless daily limit was used up. Add `OPENALEX_API_KEY` to `.env`.

---

## 7. Settings

| Setting | Where | Value | Effect |
|---|---|---|---|
| `EMBEDDING_MODEL` | `config.py` (and the `Dockerfile` ARG) | `BAAI/bge-small-en-v1.5` | Which embedding model |
| `EMBEDDING_MAX_CHARS` | `config.py` | 2000 | Text cap per paper |
| `cluster_similarity_threshold` | `Settings` | 0.05 | Higher → more, smaller clusters, more unclustered |
| `min_cluster_size` | `Settings` | 2 | Smaller groups become unclustered |
| `cluster_threshold_step` | `Settings` | 0.05 | How far a redo moves the threshold |
| `ABSTRACT_CHARS_FOR_LABELS` | `clusterer.py` | 300 | How much abstract the labeller sees |
| `grade_pass_mark` / `max_redo_per_stage` | `Settings` | 7 / 1 | Grading pass mark and redo count |
| `EMBEDDING_CACHE_DIR` | environment | unset locally; `/app/models` in Docker | Where the model files live |

---

## 8. What gets logged and stored

- **Trace (`logs/trace-<run_id>.jsonl`, agent `clusterer`):**
  - `group papers`: number of groups, unclustered count, sizes, threshold, model, embedding time, and whether a grader fix moved the threshold
  - `llm call ClusterLabels`: model, tokens, Nightshift cache status
  - `label clusters`: only when groups were dropped as incoherent or got a fallback label
  - the grader's events follow
- **World Model (`logs/world-<run_id>.json`, also `GET /world/{run_id}`):**
  - cluster entities with label and rationale
  - `member-of` and `unclustered-in` edges
  - grade facts on the `clusters` stage entity
- **`/run` output:**
  - `clusters`
  - `unclustered_paper_ids`
  - `paper_map.nodes` (type `cluster`) and `paper_map.edges` (type `member-of`)
  - `paper_map.unclustered`

---

## 9. Tests and tools

| What | Command / file |
|---|---|
| Clusterer tests, with embeddings and the LLM faked: average linkage (including the chaining case), threshold moves, labelling, incoherent drops, fallback labels, unclustered in the orchestrator, Dockerfile/config model match | `tests/test_clusterer.py` |
| Calibrate the threshold on real papers | `scripts/check_threshold.py` |
| Everything | `.venv/bin/python -m pytest` |

---

## 10. Limitations and open questions

**For you to decide:**
1. Keep mean-centering + 0.05 (decisions 1–2)? If so, `ARCHITECTURE.md` and its diagram need updating from "≥ 0.7".
2. Should the grader return a structured instruction (e.g. `{"action": "split", "cluster": "C1"}`) instead of free text? That would replace keyword matching (decision 5). It fits the grading-agent step.
3. Incoherent groups: drop them (current) or keep them as "Mixed"?

**Known limitations:**
- `bge-small` is a general-purpose model, not trained on scientific papers. The live clusters were sensible, but a science-specific model (SPECTER) might separate fine sub-fields better, at the cost of PyTorch.
- Labels come from titles and the start of abstracts only, so they describe what papers are *about*, not what they *find*.
- Labels are LLM-generated, so they vary between runs; the grouping itself is deterministic.
- Full text at High and Ultra isn't used yet.
- The threshold was calibrated on 3 ML-related topics.
