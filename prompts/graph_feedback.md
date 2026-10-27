# Revise a research map from human feedback

Use the original research question, the existing map, the human's feedback and the supplied original-source spans
to propose revised clusters. Treat the feedback as a request to investigate, not as evidence that a scientific claim
is true. Preserve every supplied paper exactly once. Return exactly one main cluster, foundation background where
supported, and side clusters for other coherent subtopics. You may split, merge, rename or move papers when the
feedback and original sources justify it. Preserve approved structure when still supported.

For every paper in a multi-paper cluster, cite at least one of that paper's supplied span IDs. Do not invent text,
paper IDs, span IDs, results or citations. Retain a paper with no quotable source as a separate uncertain singleton.
Each label must describe its actual membership. Explain the changes in the rationale. If requested changes cannot
be supported, keep the supported grouping and explain that constraint. Output JSON matching the supplied schema.
