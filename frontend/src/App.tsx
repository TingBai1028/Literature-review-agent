import { useRef, useState } from "react";
import { ChevronDown, LoaderCircle, Menu, Play, X } from "lucide-react";
import { request, messageOf, ApiError } from "./api";
import { DialogNotice } from "./components/Dialog";
import { useWorkspace } from "./useWorkspace";
import type { Filter, MapResult, Move, Paper, Plan, Selection } from "./types";
import { TopicSidebar } from "./components/TopicSidebar";
import { LiteratureGraph } from "./components/LiteratureGraph";
import { Inspector } from "./components/Inspector";
import { ReviewPanel } from "./components/ReviewPanel";
import { ActivityFeed } from "./components/ActivityFeed";
import { ReasoningPanel } from "./components/ReasoningPanel";
import { PanelHandle, usePanels } from "./components/PanelHandle";
import { Provenance } from "./components/Provenance";
import {
  buildingMap,
  newRunId,
  overlay,
  useRunEvents,
  type RunEvent,
} from "./events";
import {
  MovePreview,
  NewMapDialog,
  VersionDialog,
} from "./components/MapDialogs";
export default function App() {
  const ws = useWorkspace();
  const [tab, setTab] = useState<Tab>("map");
  // A run in progress (spec A): its events drive the live map and the activity feed.
  const [live, setLive] = useState<Live | null>(null);
  const events = useRunEvents(live?.runId ?? null);
  const [dialog, setDialog] = useState<"versions" | "new" | null>(null);
  const [busy, setBusy] = useState("");
  const busyRef = useRef(false);
  const [notice, setNotice] = useState("");
  const operate = async (label: string, action: () => Promise<void>) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(label);
    setNotice("");
    try {
      await action();
    } catch (e) {
      setNotice(messageOf(e));
      if (e instanceof ApiError && e.status === 409 && ws.data) {
        try {
          await ws.open(ws.data.map.run_id);
        } catch {
          /* Keep the original conflict visible. */
        }
      }
    } finally {
      busyRef.current = false;
      setBusy("");
    }
  };
  const data = ws.data;
  const editable =
    !!data &&
    data.map.run_id === data.versions.active_head.run_id &&
    data.map.sample_mode === ws.config.sample_mode;
  const create = (
    q: string,
    effort: string,
    papers: Paper[],
    backup: Paper[] = [],
  ) =>
    void operate("Building the map", async () => {
      let selected = papers;
      if (
        (effort === "high" || effort === "ultra" || effort === "pro") &&
        papers === data?.papers
      ) {
        selected = (
          await request<{ papers: Paper[] }>(
            `/cluster/${data.map.run_id}/papers?include_full_text=true`,
          )
        ).papers;
      }
      const runId = newRunId();
      setDialog(null);
      setTab("map");
      setLive({
        runId,
        base: null,
        papers: selected,
        question: q,
        title: "Building the map",
      });
      let built: MapResult;
      try {
        built = await request<MapResult>("/cluster", {
          method: "POST",
          body: {
            run_id: runId,
            input: {
              query: q,
              effort,
              papers: selected,
              backup_papers: backup,
            },
          },
          timeout: (ws.config.run_timeout_s + 120) * 1000,
        });
        await ws.open(built.run_id);
      } finally {
        setLive(null);
      }
      // One click builds the whole map: Graph 1 (connections) and then Graph 2 (gaps) follow straight away, each
      // shown as soon as it is ready. Incomplete maps can continue from the map's recovery action.
      if (built.status !== "partial") {
        await analyzeMap(await request<MapResult>(`/cluster/${built.run_id}`), selected);
      }
    });
  // Spec F5: swap the side papers for the next-best backup papers; main and foundation stay.
  const refresh = () =>
    data &&
    void operate("Swapping in new papers", async () => {
      const runId = newRunId();
      setLive({
        runId,
        base: data.map,
        papers: data.papers,
        question: data.map.question,
        title: "Swap papers",
      });
      const map = await request<MapResult>(
        `/cluster/${data.map.run_id}/refresh`,
        {
          method: "POST",
          body: {
            expected_version_token: data.map.version_token,
            run_id: runId,
          },
          timeout: (ws.config.run_timeout_s + 120) * 1000,
        },
      ).finally(() => setLive(null));
      await ws.open(map.run_id);
      setNotice(
        `Swapped in ${map.refresh?.swapped_in.length ?? 0} backup papers; the main and foundation clusters are unchanged.` +
          " Choose Continue analysis on the map to update connections and research gaps.",
      );
    });
  // Spec E: Graph 1 (paper edges) is opened as soon as it is ready; Graph 2 (gaps) follows on that version.
  const runStage = (
    map: MapResult,
    stage: "connections" | "gaps",
    papers: Paper[],
  ) => {
    const runId = newRunId();
    setLive({
      runId,
      base: map,
      papers,
      question: map.question,
      title:
        stage === "connections" ? "Graph 1: finding paper connections" : "Graph 2: finding research gaps",
    });
    return request<MapResult>(`/cluster/${map.run_id}/analyze`, {
      method: "POST",
      body: {
        expected_version_token: map.version_token,
        request_id: crypto.randomUUID().replaceAll("-", ""),
        stages: [stage],
        run_id: runId,
      },
      timeout: (ws.config.run_timeout_s + 120) * 1000,
    }).finally(() => setLive(null));
  };
  const analyzeMap = async (start: MapResult, papers: Paper[]) => {
    let map = start;
    if (!map.analysis?.completed_stages?.includes("connections")) {
      setBusy("Finding paper connections (Graph 1)");
      map = await runStage(map, "connections", papers);
      await ws.open(map.run_id);
      if (map.status === "partial") {
        setNotice(
          "Finished results were kept. The previous version stays active; open this unfinished version to continue the analysis.",
        );
        return;
      }
    }
    setBusy("Graph 1 is ready to browse; finding research gaps (Graph 2)");
    map = await runStage(map, "gaps", papers);
    await ws.open(map.run_id);
    setNotice(
      map.status === "partial"
        ? "Paper connections were kept; research gaps did not finish. Choose Continue analysis on the map to finish."
        : "Graph 2 (research gaps) is ready. Switch to \"Graph 2 · Gaps\" to view it.",
    );
  };
  const analyze = () =>
    data &&
    void operate("Finding paper connections (Graph 1)", () =>
      analyzeMap(data.map, data.papers),
    );
  return (
    <DialogNotice.Provider value={notice}>
      <div className="app-shell">
        <header className="app-header">
          <a className="wordmark" href="/">
            Literature Map
          </a>
          <nav className="top-nav" aria-label="Main navigation">
            <button
              className={tab === "map" ? "active" : ""}
              aria-pressed={tab === "map"}
              onClick={() => setTab("map")}
              aria-label="Paper map"
            >
              <span className="nav-qualifier">Paper </span>
              map
            </button>
            <button
              className={tab === "review" ? "active" : ""}
              aria-pressed={tab === "review"}
              onClick={() => setTab("review")}
              aria-label="Human review"
              disabled={!data}
            >
              <span className="nav-qualifier">Human </span>
              review
            </button>
            <button
              className={tab === "reasoning" ? "active" : ""}
              aria-pressed={tab === "reasoning"}
              onClick={() => setTab("reasoning")}
              disabled={!data}
            >
              Reasoning
            </button>
          </nav>
          <div className="header-actions">
            <button
              className="text-button"
              onClick={() => setDialog("new")}
              disabled={!!busy}
              title="Build a map for a new research question"
            >
              New map
            </button>
            <button
              className="text-button history-button"
              onClick={() => setDialog("versions")}
              disabled={!data || !!busy}
            >
              Versions
            </button>
          </div>
        </header>
        {data && (
          <section className="question-bar">
            <h1 title={data.map.question}>{data.map.question}</h1>
            <span className="map-counts">
              {data.papers.length} papers ·{" "}
              {data.map.clusters.filter((c) => c.kind === "main").length} main
              ·{" "}
              {data.map.clusters.filter((c) => c.kind === "foundation").length}{" "}
              foundation ·{" "}
              {
                data.map.clusters.filter(
                  (c) => c.kind !== "main" && c.kind !== "foundation",
                ).length
              }{" "}
              side clusters
            </span>
          </section>
        )}
        {(notice ||
          ws.error ||
          data?.map.sample_mode ||
          (data && data.map.sample_mode !== ws.config.sample_mode) ||
          busy) && (
          <div
            className={`notice-bar ${notice || ws.error ? "error" : ""}`}
            role={notice || ws.error ? "alert" : "status"}
          >
            {notice ||
              ws.error ||
              busy ||
              (data?.map.sample_mode
                ? "Sample mode: clusters, similarities and grades are placeholders."
                : "The server is in sample mode. Real maps can be read; switch to real mode to run analysis or move papers.")}
            {notice && (
              <button
                className="icon-button"
                aria-label="Dismiss notice"
                onClick={() => setNotice("")}
              >
                <X size={16} />
              </button>
            )}
          </div>
        )}
        {live && !live.base ? (
          <LiveBuild
            live={live}
            events={events}
            sample={ws.config.sample_mode}
          />
        ) : ws.loading ? (
          <main className="center-message">
            <LoaderCircle className="spin" size={24} />
            <p>Loading the map and sources…</p>
          </main>
        ) : !data ? (
          <main className="empty-workspace">
            <h1>Start from papers, connect research questions.</h1>
            <p>Enter a research question to search for papers, review them, then build a research map with source evidence you can inspect.</p>
            <button className="primary-button" onClick={() => setDialog("new")}>
              New map
            </button>
            {ws.error && <p className="inline-error">{ws.error}</p>}
          </main>
        ) : (
          <WorkspaceView
            key={data.map.run_id}
            data={data}
            tab={tab}
            setTab={setTab}
            editable={editable}
            busy={!!busy}
            onOperation={operate}
            onOpen={ws.open}
            onNotice={setNotice}
            timeout={(ws.config.run_timeout_s + 120) * 1000}
            live={live?.base ? { ...live, events } : null}
            onSwap={refresh}
            onContinueAnalysis={analyze}
            analysisDisabled={
              data.map.sample_mode !== ws.config.sample_mode ||
              (!editable && data.map.status !== "partial")
            }
          />
        )}
        {data && (
          <footer className="workspace-footer">
            <div className="version-selector">
              <strong>Current view</strong>
              <label>
                <span className="sr-only">Choose a map version</span>
                <select
                  value={ws.runId}
                  disabled={!!busy}
                  onChange={(e) => ws.setRunId(e.target.value)}
                >
                  {ws.catalog.map((m) => (
                    <option value={m.run_id} key={m.run_id}>
                      {m.sample_mode ? "Sample · " : ""}v{m.revision}{" "}
                      {m.active ? "· active " : ""}· {m.run_id}
                    </option>
                  ))}
                </select>
                <ChevronDown size={13} />
              </label>
            </div>
            {data.map.warnings.length > 0 && (
              <details className="quality-notes">
                <summary>Quality warnings {data.map.warnings.length}</summary>
                <div>
                  {data.map.warnings.map((w, i) => (
                    <p key={i}>{w}</p>
                  ))}
                </div>
              </details>
            )}
          </footer>
        )}
        {dialog === "new" && (
          <NewMapDialog
            papers={data?.papers ?? []}
            question={data?.map.question ?? ""}
            sample={ws.config.sample_mode}
            busy={!!busy}
            timeout={(ws.config.run_timeout_s + 120) * 1000}
            onCreate={create}
            onClose={() => setDialog(null)}
          />
        )}
        {dialog === "versions" && data && (
          <VersionDialog
            map={data.map}
            versions={data.versions}
            catalog={ws.catalog}
            busy={!!busy}
            onClose={() => setDialog(null)}
            onRefresh={() =>
              void operate("Refreshing versions", async () => {
                await ws.open(data.map.run_id);
              })
            }
            onView={(id) => {
              setDialog(null);
              void ws.open(id);
            }}
            onActivate={(id) =>
              void operate("Switching the active version", async () => {
                await request(`/cluster/${data.map.root_run_id}/activate`, {
                  method: "POST",
                  body: {
                    target_run_id: id,
                    expected_head_run_id: data.versions.active_head.run_id,
                    expected_head_version_token:
                      data.versions.active_head.version_token,
                  },
                });
                setDialog(null);
                await ws.open(id);
              })
            }
          />
        )}
      </div>
    </DialogNotice.Provider>
  );
}
function WorkspaceView({
  data,
  tab,
  setTab,
  editable,
  busy,
  onOperation,
  onOpen,
  onNotice,
  timeout,
  live,
  onSwap,
  onContinueAnalysis,
  analysisDisabled,
}: {
  data: NonNullable<ReturnType<typeof useWorkspace>["data"]>;
  tab: Tab;
  setTab: (v: Tab) => void;
  editable: boolean;
  busy: boolean;
  onOperation: (label: string, action: () => Promise<void>) => Promise<void>;
  onOpen: (id: string) => Promise<void>;
  onNotice: (text: string) => void;
  timeout: number;
  live: (Live & { events: RunEvent[] }) | null;
  onSwap: () => void;
  onContinueAnalysis: () => void;
  analysisDisabled: boolean;
}) {
  // During an analysis or refresh the map shows the base version plus everything accepted so far (A2, A4).
  const map = live ? overlay(data.map, live.events) : data.map;
  const { papers } = data;
  const [selection, setSelection] = useState<Selection | null>({
    type: "paper",
    id:
      map.clusters.find((c) => c.kind === "main")?.paper_ids[0] ??
      papers[0]?.id,
  });
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [moves, setMoves] = useState<Move[]>([]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [mobile, setMobile] = useState(false);
  const panels = usePanels();
  const changeFilter = (f: Filter) => {
    setFilter(f);
    if (f === "connections")
      setSelection(
        map.connections[0]
          ? { type: "connection", id: map.connections[0].id }
          : null,
      );
    if (f === "gaps")
      setSelection(map.gaps[0] ? { type: "gap", id: map.gaps[0].id } : null);
  };
  return (
    <>
      {tab === "review" ? (
        <ReviewPanel
          map={map}
          timeout={timeout}
          onOperation={onOperation}
          onOpen={onOpen}
          onNotice={onNotice}
        />
      ) : tab === "reasoning" ? (
        <ReasoningPanel
          map={data.map}
          versions={data.versions}
          live={live?.events ?? []}
        />
      ) : (
        <main className={`workspace-grid${panels.className}`} style={panels.style}>
          <button
            className="mobile-topic-toggle"
            onClick={() => setMobile((v) => !v)}
            aria-label="Toggle topic navigation"
          >
            <Menu size={17} />
            Topics
          </button>
          <TopicSidebar
            clusters={map.clusters}
            papers={papers}
            selection={selection}
            search={search}
            onSearch={setSearch}
            onSelect={(s) => {
              setSelection(s);
              setMobile(false);
            }}
            mobileOpen={mobile}
          />
          <PanelHandle side="left" panels={panels.panels} set={panels.set} />
          <LiteratureGraph
            map={map}
            papers={papers}
            selection={selection}
            onSelect={setSelection}
            filter={filter}
            onFilter={changeFilter}
            search={search}
            onReview={() => setTab("review")}
            onContinueAnalysis={busy ? undefined : onContinueAnalysis}
            analysisDisabled={analysisDisabled}
            onSwap={onSwap}
            swapDisabled={busy || !editable}
          />
          <PanelHandle side="right" panels={panels.panels} set={panels.set} />
          <Inspector
            map={map}
            papers={papers}
            selection={selection}
            onSelect={setSelection}
            moves={moves}
            canEdit={editable && !busy}
            onMove={(pid, target) => {
              setMoves((old) => [
                ...old.filter((m) => m.paper_id !== pid),
                ...(target
                  ? [{ paper_id: pid, target_cluster_id: target }]
                  : []),
              ]);
              setPlan(null);
            }}
            onReview={() => setTab("review")}
            top={
              live && (
                <ActivityFeed
                  side
                  events={live.events}
                  title={live.title}
                  onShowAll={() => setTab("reasoning")}
                />
              )
            }
          >
            <Provenance
              map={map}
              papers={papers}
              selection={selection}
              onShowReasoning={() => setTab("reasoning")}
            />
          </Inspector>
        </main>
      )}
      {tab === "map" && (
        <div className="move-bar">
          {moves.length > 0 && (
            <>
              <span>{moves.length} papers to move</span>
              <button
                className="text-button small"
                disabled={busy}
                onClick={() => setMoves([])}
              >
                Clear
              </button>
            </>
          )}
          <button
            className="secondary-button"
            disabled={!moves.length || busy || !editable}
            onClick={() =>
              void onOperation("Checking move constraints", async () =>
                setPlan(
                  await request<Plan>(
                    `/cluster/${map.run_id}/regenerate/preview`,
                    { method: "POST", body: { moves } },
                  ),
                ),
              )
            }
          >
            <Play size={13} fill="currentColor" />
            Preview move
          </button>
        </div>
      )}
      {plan && (
        <MovePreview
          plan={plan}
          map={map}
          canApply={editable}
          busy={busy}
          onClose={() => setPlan(null)}
          onApply={() =>
            void onOperation("Creating a new version", async () => {
              const child = await request<MapResult>(
                `/cluster/${map.run_id}/regenerate`,
                {
                  method: "POST",
                  body: { preview_id: plan.preview_id },
                  timeout,
                },
              );
              setPlan(null);
              setMoves([]);
              await onOpen(child.run_id);
            })
          }
        />
      )}
    </>
  );
}

type Tab = "map" | "review" | "reasoning";
interface Live {
  runId: string;
  base: MapResult | null; // null while a new map is being built
  papers: Paper[];
  question: string;
  title: string;
}

/** A new map being built (spec A2): papers appear, glide into their clusters, then the clusters get names.
 * Pan, zoom and clicking work throughout (A4); the activity feed says which agent is working (A3). */
function LiveBuild({
  live,
  events,
  sample,
}: {
  live: Live;
  events: RunEvent[];
  sample: boolean;
}) {
  const { map, neighbors } = buildingMap(
    live.runId,
    live.question,
    live.papers,
    events,
    sample,
  );
  const [selection, setSelection] = useState<Selection | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const panels = usePanels();
  const paper = live.papers.find(
    (p) => selection?.type === "paper" && p.id === selection.id,
  );
  return (
    <main className={`workspace-grid live-build${panels.className}`} style={panels.style}>
      <aside className="topic-sidebar">
        <h2>{live.title}</h2>
        <p className="muted small">{live.question}</p>
        <p className="small">{live.papers.length} papers are being grouped and named.</p>
      </aside>
      <PanelHandle side="left" panels={panels.panels} set={panels.set} />
      <LiteratureGraph
        map={map}
        papers={live.papers}
        neighbors={neighbors}
        selection={selection}
        onSelect={setSelection}
        filter={filter}
        onFilter={setFilter}
        search=""
        onReview={() => undefined}
      />
      <PanelHandle side="right" panels={panels.panels} set={panels.set} />
      <aside className="inspector">
        <ActivityFeed side events={events} title={live.title} />
        {paper ? (
          <>
            <h3 className="paper-title">{paper.title}</h3>
            <p className="paper-meta">
              {paper.year ?? "Year unknown"} · {paper.source}
            </p>
            <p className="small">{paper.abstract}</p>
          </>
        ) : (
          <p className="muted">The map is being built; click a paper to read its abstract meanwhile.</p>
        )}
      </aside>
    </main>
  );
}
