import { useState } from "react";
import { Check, RefreshCw, Upload } from "lucide-react";
import { ActivityFeed } from "./ActivityFeed";
import { Dialog } from "./Dialog";
import { SearchReview, useSearchReview } from "./SearchReview";
import type { CatalogItem, MapResult, Paper, Plan, Versions } from "../types";
export function MovePreview({
  plan,
  map,
  busy,
  canApply,
  onApply,
  onClose,
}: {
  plan: Plan;
  map: MapResult;
  busy: boolean;
  canApply: boolean;
  onApply: () => void;
  onClose: () => void;
}) {
  return (
    <Dialog title="Preview cluster changes" onClose={onClose} busy={busy}>
      <div className="dialog-body">
        <p className="muted">
          Check where the papers land after all the moves. The current version
          is kept and can be restored from Versions.
        </p>
        {plan.changes.map((c) => (
          <div className="change-row" key={c.cluster_id}>
            <strong>
              {map.clusters.find((x) => x.id === c.cluster_id)?.label ??
                c.cluster_id}
            </strong>
            <span>
              {c.before.length} → {c.after.length} papers
              {!c.after.length ? " · the empty cluster will be removed" : ""}
            </span>
          </div>
        ))}
        <p className="muted small">
          Relabels {plan.relabel_cluster_ids.length} side clusters and reuses{" "}
          {plan.reused_label_cluster_ids.length} labels. Active connections and
          hypotheses are checked again against the final clusters.
        </p>
        {!plan.applicable && (
          <div className="inline-error" role="alert">
            {plan.errors.map((e, i) => (
              <p key={i}>{e}</p>
            ))}
          </div>
        )}
      </div>
      <footer className="dialog-actions">
        <button className="secondary-button" disabled={busy} onClick={onClose}>
          Cancel
        </button>
        <button
          className="primary-button"
          disabled={!plan.applicable || busy || !canApply}
          onClick={onApply}
        >
          {busy ? "Creating a new version…" : "Apply as a new version"}
        </button>
      </footer>
    </Dialog>
  );
}
export function VersionDialog({
  map,
  versions,
  catalog,
  busy,
  onView,
  onActivate,
  onRefresh,
  onClose,
}: {
  map: MapResult;
  versions: Versions;
  catalog: CatalogItem[];
  busy: boolean;
  onView: (id: string) => void;
  onActivate: (id: string) => void;
  onRefresh: () => void;
  onClose: () => void;
}) {
  return (
    <Dialog title="Versions" onClose={onClose} wide busy={busy}>
      <div className="dialog-body">
        <div className="version-intro">
          <p className="muted">
            Viewing history does not change the active version. It changes only
            when you make a version active.
          </p>
          <button className="quiet-button" onClick={onRefresh} disabled={busy}>
            <RefreshCw size={15} />
            Refresh
          </button>
        </div>
        {[...versions.versions].reverse().map((v) => (
          <div className="version-row" key={v.run_id}>
            <div>
              <strong>
                v{v.revision} ·{" "}
                {v.status === "partial"
                  ? "Unfinished"
                  : catalog.find((m) => m.run_id === v.run_id)?.stage ===
                      "findings"
                    ? "Analysed"
                    : "Cluster map"}
                {versions.active_head.run_id === v.run_id && (
                  <span className="active-version">
                    <Check size={13} />
                    Active
                  </span>
                )}
              </strong>
              <code>{v.run_id}</code>
            </div>
            <div className="version-buttons">
              <button
                className="quiet-button"
                disabled={busy || map.run_id === v.run_id}
                onClick={() => onView(v.run_id)}
              >
                View
              </button>
              <button
                className="secondary-button"
                disabled={
                  busy ||
                  v.status !== "done" ||
                  v.run_id === versions.active_head.run_id
                }
                onClick={() => onActivate(v.run_id)}
              >
                Make active
              </button>
            </div>
          </div>
        ))}
      </div>
    </Dialog>
  );
}
export function NewMapDialog({
  papers,
  question,
  busy,
  sample,
  timeout,
  onCreate,
  onClose,
}: {
  papers: Paper[];
  question: string;
  busy: boolean;
  sample: boolean;
  timeout: number;
  onCreate: (q: string, effort: string, p: Paper[], backup?: Paper[]) => void;
  onClose: () => void;
}) {
  const [mode, setMode] = useState<"search" | "import">("search");
  const [query, setQuery] = useState(question);
  const [effort, setEffort] = useState("fast");
  const [source, setSource] = useState<Paper[]>(papers);
  const [error, setError] = useState("");
  const search = useSearchReview(query, effort, timeout);
  const locked = busy || search.loading;
  const close = () => {
    search.cancel();
    onClose();
  };
  const [name, setName] = useState(
    papers.length
      ? `Use the current ${papers.length} papers`
      : "No paper records chosen yet",
  );
  const upload = async (file: File | undefined) => {
    if (!file) return;
    setError("");
    try {
      const raw = JSON.parse(await file.text());
      const ps = Array.isArray(raw)
        ? raw
        : (raw.input?.papers ?? raw.output?.papers ?? raw.papers);
      if (
        !Array.isArray(ps) ||
        !ps.length ||
        !ps.every(
          (p) =>
            typeof p.id === "string" &&
            typeof p.title === "string" &&
            typeof p.source === "string",
        )
      )
        throw Error("Expected paper-record JSON with id, title and source.");
      setSource(ps);
      setName(`${file.name} · ${ps.length} papers`);
      const importedQuery =
        raw.input?.query ??
        raw.query ??
        raw.output?.plan?.question ??
        raw.output?.question;
      if (typeof importedQuery === "string" && importedQuery.trim())
        setQuery(importedQuery);
      const importedEffort = raw.input?.effort ?? raw.effort;
      if (
        ["fast", "pro", "normal", "medium", "high", "ultra"].includes(
          importedEffort,
        )
      )
        setEffort(importedEffort);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not read the file");
    }
  };
  const reviewed = mode === "search" && search.result?.status === "ok";
  const submit = () => {
    setError("");
    if (!query.trim()) {
      setError("Enter a research question.");
      return;
    }
    if (mode === "search" && !reviewed) {
      void search.run();
      return;
    }
    const chosen = mode === "search" ? search.selected : source;
    const cap = (
      {
        fast: 50,
        pro: 50,
        normal: 30,
        medium: 60,
        high: 100,
        ultra: 150,
      } as Record<string, number>
    )[effort];
    if (!chosen.length) {
      setError(
        mode === "search"
          ? "Keep at least one paper."
          : "Choose paper records.",
      );
      return;
    }
    if (chosen.length > cap) {
      setError(
        `This level supports at most ${cap} papers; choose another level or other records.`,
      );
      return;
    }
    onCreate(
      search.result?.plan?.question ?? query.trim(),
      effort,
      chosen,
      mode === "search" ? (search.result?.backup_papers ?? []) : [],
    );
  };
  return (
    <Dialog
      title="New research map"
      onClose={close}
      busy={busy}
      wide={reviewed}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <div className="dialog-body">
          <div
            className="segmented mode-switch"
            role="group"
            aria-label="Paper source"
          >
            {(
              [
                ["search", "Search online"],
                ["import", "Import records"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={mode === value ? "active" : ""}
                aria-pressed={mode === value}
                disabled={locked}
                onClick={() => {
                  setMode(value);
                  setError("");
                }}
              >
                {label}
              </button>
            ))}
          </div>
          <label className="form-field">
            Research question
            <textarea
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                search.reset();
              }}
              rows={3}
              placeholder="For example: How does LoRA improve machine translation for low-resource languages? You can add years, citation counts or paper types."
              required
              disabled={locked}
            />
          </label>
          <label className="form-field">
            Effort
            <select
              value={effort}
              disabled={locked}
              onChange={(e) => {
                setEffort(e.target.value);
                search.reset();
              }}
            >
              <option value="fast">
                Fast · retrieves ~300 papers, shows the 50 most relevant
              </option>
              <option value="pro">
                Pro · retrieves ~1,000 papers, shows 50 and reads full text
              </option>
              {!["fast", "pro"].includes(effort) && (
                <option value={effort}>{effort} (legacy level)</option>
              )}
            </select>
          </label>
          {mode === "search" && search.loading && (
            <ActivityFeed
              inline
              events={search.events}
              title="Searching for papers"
            />
          )}
          {mode === "search" ? (
            <SearchReview search={search} />
          ) : (
            <label className="upload-field">
              <Upload size={22} />
              <span>{name}</span>
              <small>Choose saved search results or paper-record JSON</small>
              <input
                type="file"
                accept=".json,application/json"
                onChange={(e) => void upload(e.target.files?.[0])}
              />
            </label>
          )}
          <p className="muted small">
            {sample
              ? "Sample mode: search uses the saved sample papers; clusters and grades are placeholders."
              : mode === "search"
                ? "Search calls the Planner and OpenAlex and stores papers through Zetaris; no map is built until you approve the papers."
                : "A new map calls the configured model. High / Ultra use full text from the records when provided, otherwise abstracts."}
          </p>
          {(error || search.error) && (
            <p className="inline-error" role="alert">
              {error || search.error}
            </p>
          )}
        </div>
        <footer className="dialog-actions">
          <button
            className="secondary-button"
            type="button"
            onClick={close}
            disabled={busy}
          >
            Cancel
          </button>
          <button className="primary-button" disabled={locked} type="submit">
            {search.loading
              ? "Searching…"
              : busy
                ? "Building the map…"
                : mode === "search" && !reviewed
                  ? "Search papers"
                  : mode === "search"
                    ? `Build the map from ${search.selected.length} kept papers`
                    : "Build map"}
          </button>
        </footer>
      </form>
    </Dialog>
  );
}
