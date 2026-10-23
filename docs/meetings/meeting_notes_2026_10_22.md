# Meeting Notes: Feature Discussion for the Academic Literature Search Tool, 22 October 2026

Recording time: 2026-10-22 16:43 – 2026-10-22 20:05

# Summary

The meeting brainstormed the end-to-end feature design of the academic literature search agent, and settled the rules, parameters and next steps for each module:

- **Product entry point and basic interaction rules**
  - **Input interface design**
    - Core interaction: a single chat box like ChatGPT. No Google Scholar-style pre-filter controls for year, citation count, etc.; users describe what they need in natural language.

    - No valid topic: if the user's input doesn't mention a research topic, don't return an error. Use friendly guiding wording to prompt the user to add their core research direction.

  - **Search effort levels**
    - Levels: 3–4 effort levels, keeping the top "Ultra" level. Each level has a different token limit, and search time is roughly proportional to the level.

    - How levels apply: lower levels (Normal, Medium) work from paper metadata only; higher levels (High, Ultra) download the full PDF for in-depth analysis.

- **Rules for each module in the core flow**
  - **Planner module**
    - Core function: parse the user's natural-language request and output structured search rules, including topic, year range, paper type and citation requirements.

    - Defaults: when the user doesn't specify filters, return relevant papers from the past 5 years by default, covering both review and primary research papers.

    - Success criterion: the search rules it outputs can be used directly by the next (retrieval) step without errors.

  - **Retriever module**
    - Search scope: users who aren't signed in can only search open-access (OA) papers; users signed in with their university academic account can access more permission-protected academic resources.

    - Post-search guidance: for users with vague requests, first return a summary list of a small number of highly relevant papers, then guide the user to add details such as year, citation count or paper type. Supports going back to the Planner to adjust the search rules.

    - Not needed now: no extra agent self-check scoring step for retrieval. This is lower priority and may be added in a later iteration.

  - **Cluster module**
    - Clustering rule: based on established open-source paper similarity algorithms, use cosine similarity 0.7 as the threshold; papers above the threshold go in the same category and get a matching label.

    - Validation: an independent scoring agent checks the clustering result; it passes when the score reaches a preset threshold.

    - Next step: the developer responsible for this module will research and choose the specific algorithm.

  - **Contradiction module (changed):** after discussion, the module's definition was judged too vague and likely to introduce AI-fabricated content. Following the principle "don't add entities without necessity", this feature won't be implemented for now.

  - **Gap Finder module:** only looks for research gaps between papers within the same cluster whose similarity falls in a reasonable range, to avoid meaningless results from papers that are too weakly related.

# Chapters

00:02 **Choosing the interaction style for the literature search interface**

> Both sides discussed how users should enter input. The initial idea was a GPT-style chat box; adding Google Scholar-style filters (year, language, citation count, region) was also mentioned. They agreed that since AI is already involved in the search, users can state their needs precisely in one sentence, so no extra filters are needed. Decision: a pure chat-box input.

01:43 **Planner module function and flow**

> This section mapped out the core flow: after the input box receives the user's prompt, the planner analyses the request and outputs search requirements in JSON, which are passed to the retriever that finds papers. Unstated search conditions default to the last 5 years with no restriction on paper type. They also added a mechanism where, after results are generated, the user can add requests and the system searches again using the conversation context.

06:37 **Planner task completion rules and effort levels**

> Discussion of when the paper-search planner's task counts as complete. They agreed it can't simply be "returned N papers". Final decision: use a single model, with 3–4 effort levels at different token limits so users can choose how much compute to spend. When the set tokens are used up, the search can end, or the user can choose to continue.

14:54 **Planner failure cases and guidance when there's no topic**

> Discussion of planner failure cases. The minimum requirement to run is that the user provides a search topic. If the user only asks to find papers without giving a topic, don't return an error; use a friendly conversational prompt to ask for the topic. Once there's a topic, the search starts, and the user can later be guided to add filters such as year range, citation count and paper type.

18:21 **Interaction strategy when the chat box has no explicit conditions**

> Discussion of the academic agent chat box's search logic when the user doesn't specify year, citation count or other filters. They weighed how tedious it is to ask the user directly, and what the research community generally assumes. Final decision: a guided approach. First output default relevant results, then ask whether the user has preferences on time range, citation count, etc.

23:38 **Designing the steps of the literature search agent flow**

> Discussion of the paper-collection flow. The step that guides the user to confirm preferences comes after papers are collected, between retrieval and clustering. It returns a summary of topic-relevant papers with guiding questions to get feedback and adjust the search. They also concluded there's no need yet for an extra agent to score retrieval results; that can be added later.

31:11 **Paper clustering and related features**

> Discussion of clustering. An agent groups papers by research direction and labels them. They settled the clustering module's input for each effort level, agreed to cluster using a public paper-similarity algorithm with a threshold, and planned a scoring agent to check clustering quality. They also mentioned later using cluster results to define the scope for finding research gaps.

53:25 **Whether to keep the contradiction feature, its definition and implementation**

> After a 10-minute break, participants discussed contradiction rules. They first defined it as a conflict between two papers in the same cluster, and initially decided to detect contradictions only between pairs of papers: multiple contradictions in one pair are drawn as one line, with details shown on click, and nothing involving three or more papers for now. They then found the concept too vague, potentially tied to issues like academic misconduct, and possibly a false problem. Following "don't add entities without necessity", they agreed to consider cutting the feature.

# Key decisions

- **Key decision:** user input interaction and initial processing logic for the academic literature search tool
  - **Problem:** when the user only gives a topic, without year, citation or paper-type filters, how to handle it without making the flow tedious, while fitting different users' needs.

  - **Options discussed:**
    - Speaker 2 proposed that if the user only gives a topic, first return 10–20 relevant papers, then guide the user to add filter preferences, instead of asking about each one up front.

    - Speaker 1 felt that year and citation count are common knowledge among researchers, so asking up front would be redundant.

    - Speaker 2 noted the product is a general academic tool with a wide audience; a guided approach meets different users' needs and also helps new users learn how to search precisely.

  - **Rationale:** keeps the product broadly usable and the flow simple, while still guiding new users.

---

- **Other decisions:**
  1. The user input interface is a single GPT-style chat box, with no extra filter controls.

  2. Searches have 3–4 token-limit effort levels, including one top level.

  3. Users who aren't signed in can only search open-access (OA) papers; signing in with a university account allows searching all papers.

  4. The clustering module uses a public similarity algorithm with a similarity threshold to group and label papers.

  5. The contradiction feature won't be implemented for now, following the principle "don't add entities without necessity".
