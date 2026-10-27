import { useEffect, useRef, useState } from "react";
import { LoaderCircle, Menu, Plus, X } from "lucide-react";
import { request, messageOf, ApiError } from "./api";
import { DialogNotice } from "./components/Dialog";
import { useWorkspace } from "./useWorkspace";
import { feedbackError } from "./feedbackWorkflow";
import type {
  FeedbackState,
  FeedbackTarget,
  Filter,
  MapResult,
  Move,
  Paper,
  Plan,
  Selection,
} from "./types";
import { TopicSidebar } from "./components/TopicSidebar";
import { LiteratureGraph } from "./components/LiteratureGraph";
import { Inspector } from "./components/Inspector";
import { MapSearch } from "./components/MapSearch";
import { FeedbackBot } from "./components/FeedbackBot";
import { QuickFeedback } from "./components/QuickFeedback";
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
          setFeedback(
            await request<FeedbackState>(
              `/cluster/${ws.data.map.run_id}/feedback`,
            ),
          );
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
  const panels = usePanels();
  const [selection, setSelection] = useState<Selection | null>(null);
  const [feedback, setFeedback] = useState<FeedbackState>({
    votes: {},
    messages: [],
  });
  const [botOpenRequest, setBotOpenRequest] = useState(0);
  const graphReady =
    !!data &&
    data.map.status === "done" &&
    ["connections", "gaps"].every((stage) =>
      data.map.analysis?.completed_stages?.includes(stage),
    );
  useEffect(() => {
    if (!data) return;
    const abort = new AbortController();
    setFeedback({ votes: {}, messages: [] });
    request<FeedbackState>(`/cluster/${data.map.run_id}/feedback`, {
      signal: abort.signal,
    })
      .then((record) => {
        if (!abort.signal.aborted) setFeedback(record);
      })
      .catch((error) => {
        if (!abort.signal.aborted) setNotice(messageOf(error));
      });
    return () => abort.abort();
  }, [data?.map.run_id]);
  const select = (next: Selection | null) => {
    setSelection(next);
    setTab("map");
    panels.set("right", { open: true });
  };
  const navigationUnavailable = !data || ws.loading || !!busy;
  const navigationMessage = busy
    ? "Reasoning and feedback will be available when processing finishes. You can keep exploring the paper map."
    : ws.loading
      ? "Loading the map. Reasoning and feedback will be available shortly."
      : !data
        ? "Create a map to explore its reasoning and give feedback."
        : "";
  const changeTab = (next: Tab) => {
    if (next !== "map" && navigationUnavailable) return;
    setTab(next);
  };
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
      setSelection(null);
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
      // One click builds the whole map: Connection graph (connections) and then Gap graph (gaps) follow straight away, each
      // shown as soon as it is ready. Incomplete maps can continue from the map's recovery action.
      if (built.status !== "partial") {
        await analyzeMap(
          await request<MapResult>(`/cluster/${built.run_id}`),
          selected,
        );
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
  // Spec E: Connection graph (paper edges) is opened as soon as it is ready; Gap graph (gaps) follows on that version.
  const runStage = (
    map: MapResult,
    stage: "connections" | "gaps",
    papers: Paper[],
    keepCurrentGraph = false,
  ) => {
    const runId = newRunId();
    setLive({
      runId,
      base: map,
      papers,
      question: map.question,
      title:
        stage === "connections"
          ? "Connection graph: finding connections"
          : "Gap graph: finding research gaps",
      keepCurrentGraph,
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
      setBusy("Building the connection graph");
      map = await runStage(map, "connections", papers);
      await ws.open(map.run_id);
      if (map.status === "partial") {
        setNotice(
          "Finished results were kept. The previous version stays active; open this unfinished version to continue the analysis.",
        );
        return;
      }
    }
    setBusy("Connection graph is ready to browse; building the gap graph");
    map = await runStage(map, "gaps", papers);
    await ws.open(map.run_id);
    setNotice(
      map.status === "partial"
        ? "Paper connections were kept; research gaps did not finish. Choose Continue analysis on the map to finish."
        : 'Gap graph is ready. Switch to "Gap graph" to view it.',
    );
  };
  // A feedback update's unfinished finding stages, one request each like a new map, so each gets the full
  // time limit. Stops at the first unfinished result; a completed stage's missing grade is retried by the
  // next request. Returns the last version and the ID of the graph to show.
  const finishFeedbackStages = async (
    start: MapResult,
    papers: Paper[],
    currentGraphId: string,
  ) => {
    let map = start;
    const remaining: ("connections" | "gaps")[] =
      map.analysis?.completed_stages?.includes("connections")
        ? ["gaps"]
        : ["connections", "gaps"];
    for (const stage of remaining) {
      map = await runStage(map, stage, papers, map.status !== "done");
      if (map.status !== "done") break;
      await ws.open(map.run_id);
    }
    const record = await request<FeedbackState>(
      `/cluster/${map.run_id}/feedback`,
    );
    setFeedback(record);
    if (map.status === "done") setSelection(null);
    return map.status === "done"
      ? map.run_id
      : (record.update?.active_run_id ?? currentGraphId);
  };
  const analyze = () => {
    if (
      feedback.update?.status === "paused" ||
      (feedback.update?.status === "complete" &&
        feedback.update.pending.length > 0)
    ) {
      void resumeFeedback().catch((error) => setNotice(messageOf(error)));
    } else if (data) {
      void operate("Building the connection graph", () =>
        analyzeMap(data.map, data.papers),
      );
    }
  };
  const regenerateFromFeedback = async (
    text: string,
    target?: FeedbackTarget,
  ) => {
    if (feedback.update?.status === "paused") {
      setBotOpenRequest((n) => n + 1);
      throw new Error(
        "Your saved update is waiting. Resume it or keep the current graph before sending more feedback.",
      );
    }
    if (!data || busyRef.current || !editable || !graphReady)
      throw new Error(
        "Wait for the active graph to finish before giving feedback.",
      );
    let success = false;
    let failure = "";
    setTab("map");
    setBotOpenRequest((n) => n + 1);
    await operate("Updating the graph from your feedback", async () => {
      const runId = newRunId();
      try {
        if (target) {
          const record = await request<FeedbackState>(
            `/cluster/${data.map.run_id}/feedback/vote`,
            {
              method: "POST",
              body: {
                expected_version_token: data.map.version_token,
                target,
                vote: "down",
              },
            },
          );
          setFeedback(record);
        }
        setLive({
          runId,
          base: data.map,
          papers: data.papers,
          question: data.map.question,
          title: "Updating graph from feedback",
          keepCurrentGraph: true,
        });
        const out = await request<{ map: MapResult; feedback: FeedbackState }>(
          `/cluster/${data.map.run_id}/feedback/regenerate`,
          {
            method: "POST",
            body: {
              expected_version_token: data.map.version_token,
              request_id: crypto.randomUUID().replaceAll("-", ""),
              run_id: runId,
              text,
              target,
            },
            timeout: (ws.config.run_timeout_s + 120) * 1000,
          },
        );
        setFeedback(out.feedback);
        if (out.map.status === "done") {
          // The revision returns topics and the connection graph; the gap graph follows as its own request.
          setSelection(null);
          await ws.open(out.map.run_id);
          await ws.open(
            await finishFeedbackStages(out.map, data.papers, out.map.run_id),
          );
        } else {
          await ws.open(out.feedback.update?.active_run_id ?? data.map.run_id);
        }
        success = true;
      } catch (error) {
        failure = feedbackError(error);
        throw new Error(failure);
      } finally {
        setLive(null);
      }
    });
    if (!success)
      throw new Error(
        failure ||
          "The graph could not be updated. Your feedback is still here. Please try again.",
      );
  };
  const resumeFeedback = async () => {
    const update = feedback.update;
    if (!data || !update || busyRef.current) return;
    let success = false;
    let failure = "";
    setBotOpenRequest((n) => n + 1);
    await operate("Finishing your saved feedback update", async () => {
      try {
        const draft = await request<MapResult>(`/cluster/${update.run_id}`);
        setTab("map");
        await ws.open(
          await finishFeedbackStages(draft, data.papers, update.active_run_id),
        );
        success = true;
      } catch (error) {
        failure = feedbackError(error);
        throw new Error(failure);
      } finally {
        setLive(null);
      }
    });
    if (!success)
      throw new Error(
        failure ||
          "Your saved update is still available. Please try resuming again.",
      );
  };
  const keepCurrentGraph = async () => {
    const update = feedback.update;
    if (!data || !update || busyRef.current) return;
    let success = false;
    await operate("Keeping the current graph", async () => {
      const current = await request<MapResult>(
        `/cluster/${update.active_run_id}`,
      );
      if (data.map.run_id !== current.run_id && !update.can_resume) {
        await ws.open(current.run_id);
      } else {
        setFeedback(
          await request<FeedbackState>(
            `/cluster/${current.run_id}/feedback/dismiss`,
            {
              method: "POST",
              body: {
                expected_version_token: current.version_token,
                expected_update_run_id: update.run_id,
              },
            },
          ),
        );
        await ws.open(current.run_id);
      }
      success = true;
    });
    if (!success)
      throw new Error(
        "Could not switch to the current graph. Please try again.",
      );
  };
  const quickVote = (target: FeedbackTarget, vote: "up" | "down") => {
    if (!data || busyRef.current || !editable || !graphReady) return;
    if (feedback.update?.status === "paused") {
      setBotOpenRequest((n) => n + 1);
      return;
    }
    if (vote === "down") {
      void regenerateFromFeedback(
        `I do not approve this ${target.kind}. Reconsider it against the research question and the original source evidence, and improve the graph accordingly.`,
        target,
      ).catch((error) => setNotice(messageOf(error)));
    } else {
      void operate("Saving your feedback", async () => {
        const record = await request<FeedbackState>(
          `/cluster/${data.map.run_id}/feedback/vote`,
          {
            method: "POST",
            body: {
              expected_version_token: data.map.version_token,
              target,
              vote,
            },
          },
        );
        setFeedback(record);
      });
    }
  };
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
              onClick={() => changeTab("map")}
              aria-label="Paper map"
            >
              <span className="nav-qualifier">Paper </span>
              map
            </button>
            <button
              className={tab === "reasoning" ? "active" : ""}
              aria-pressed={tab === "reasoning"}
              onClick={() => changeTab("reasoning")}
              disabled={navigationUnavailable}
              aria-describedby={
                navigationMessage ? "workspace-navigation-status" : undefined
              }
              title={navigationMessage || "Read the completed run's reasoning"}
            >
              Reasoning
            </button>
          </nav>
          <MapSearch
            clusters={data?.map.clusters ?? []}
            papers={data?.papers ?? []}
            disabled={!data || !!busy || ws.loading}
            onSelect={select}
          />
          <div className="header-actions">
            <button
              className="primary-button create-map-button"
              onClick={() => setDialog("new")}
              disabled={!!busy}
              title="Build a map for a new research question"
            >
              <Plus size={18} /> Create new map
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
        {(data || live) && (
          <section className="question-bar">
            <h1 title={live?.question ?? data?.map.question}>
              {live?.question ?? data?.map.question}
            </h1>
          </section>
        )}
        {(notice ||
          ws.error ||
          (!live &&
            (data?.map.sample_mode ||
              (data && data.map.sample_mode !== ws.config.sample_mode) ||
              busy))) && (
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
        {navigationMessage && (
          <p
            id="workspace-navigation-status"
            className="navigation-status"
            role="status"
          >
            {navigationMessage}
          </p>
        )}
        {live && <ActivityFeed dock events={events} title={live.title} />}
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
            <p>
              Enter a research question to search for papers, review them, then
              build a research map with source evidence you can inspect.
            </p>
            <button className="primary-button" onClick={() => setDialog("new")}>
              <Plus size={18} /> Create new map
            </button>
            {ws.error && <p className="inline-error">{ws.error}</p>}
          </main>
        ) : (
          <WorkspaceView
            key={data.map.run_id}
            data={data}
            tab={tab}
            setTab={changeTab}
            selection={selection}
            onSelect={select}
            panels={panels}
            feedback={feedback}
            onVote={quickVote}
            onOpenFeedback={() => setBotOpenRequest((n) => n + 1)}
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
        <FeedbackBot
          map={data?.map}
          feedback={feedback}
          busy={!!busy || ws.loading}
          editable={editable}
          ready={graphReady}
          openRequest={botOpenRequest}
          onSubmit={(text) => regenerateFromFeedback(text)}
          onResume={resumeFeedback}
          onKeepCurrent={keepCurrentGraph}
          onViewDraft={() => {
            if (feedback.update)
              void ws
                .open(feedback.update.run_id)
                .catch((error) => setNotice(messageOf(error)));
          }}
          progress={
            live?.keepCurrentGraph
              ? (
                  {
                    clusterer: "Revising topics from your feedback…",
                    clusters_finder: "Revising topics from your feedback…",
                    grader: "Checking the revised graph…",
                    connection_finder: "Updating the connection graph…",
                    connections_finder: "Checking connections…",
                    gap_finder: "Updating the gap graph…",
                    gaps_finder: "Checking gaps…",
                    orchestrator: "Saving the updated graph…",
                  } as Record<string, string>
                )[events.at(-1)?.agent ?? ""] || "Applying your feedback…"
              : busy
          }
        />
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
  selection,
  onSelect,
  panels,
  feedback,
  onVote,
  onOpenFeedback,
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
  selection: Selection | null;
  onSelect: (selection: Selection | null) => void;
  panels: ReturnType<typeof usePanels>;
  feedback: FeedbackState;
  onVote: (target: FeedbackTarget, vote: "up" | "down") => void;
  onOpenFeedback: () => void;
}) {
  // During an analysis or refresh the map shows the base version plus everything accepted so far (A2, A4).
  const map =
    live && !live.keepCurrentGraph ? overlay(data.map, live.events) : data.map;
  const { papers } = data;
  const selected =
    selection &&
    (selection.type === "paper"
      ? papers.some((p) => p.id === selection.id)
      : selection.type === "cluster"
        ? map.clusters.some((c) => c.id === selection.id)
        : selection.type === "connection"
          ? map.connections.some((c) => c.id === selection.id)
          : map.gaps.some((g) => g.id === selection.id))
      ? selection
      : {
          type: "paper" as const,
          id:
            map.clusters.find((c) => c.kind === "main")?.paper_ids[0] ??
            papers[0]?.id,
        };
  const [filter, setFilter] = useState<Filter>("all");
  const [moves, setMoves] = useState<Move[]>([]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [mobile, setMobile] = useState(false);
  const changeFilter = (f: Filter) => {
    setFilter(f);
    if (f === "connections")
      onSelect(
        map.connections[0]
          ? { type: "connection", id: map.connections[0].id }
          : null,
      );
    if (f === "gaps")
      onSelect(map.gaps[0] ? { type: "gap", id: map.gaps[0].id } : null);
  };
  return (
    <>
      {tab === "reasoning" ? (
        <ReasoningPanel
          map={data.map}
          versions={data.versions}
          live={live?.events ?? []}
        />
      ) : (
        <main
          className={`workspace-grid${panels.className}`}
          style={panels.style}
        >
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
            selection={selected}
            onSelect={(s) => {
              onSelect(s);
              setMobile(false);
            }}
            mobileOpen={mobile}
          />
          <PanelHandle side="left" panels={panels.panels} set={panels.set} />
          <LiteratureGraph
            map={map}
            papers={papers}
            selection={selected}
            onSelect={onSelect}
            filter={filter}
            onFilter={changeFilter}
            search=""
            onFeedback={busy ? undefined : onOpenFeedback}
            onContinueAnalysis={busy ? undefined : onContinueAnalysis}
            analysisDisabled={analysisDisabled}
            onSwap={onSwap}
            swapDisabled={busy || !editable}
          />
          <PanelHandle side="right" panels={panels.panels} set={panels.set} />
          <Inspector
            map={map}
            papers={papers}
            selection={selected}
            onSelect={onSelect}
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
            onPreviewMove={() =>
              void onOperation("Checking move constraints", async () =>
                setPlan(
                  await request<Plan>(
                    `/cluster/${map.run_id}/regenerate/preview`,
                    { method: "POST", body: { moves } },
                  ),
                ),
              )
            }
            feedback={
              selected.type !== "paper" && (
                <QuickFeedback
                  target={{ kind: selected.type, id: selected.id }}
                  vote={feedback.votes[`${selected.type}:${selected.id}`]?.vote}
                  disabled={
                    busy ||
                    !editable ||
                    map.status !== "done" ||
                    !["connections", "gaps"].every((s) =>
                      map.analysis?.completed_stages?.includes(s),
                    )
                  }
                  onVote={onVote}
                />
              )
            }
          >
            <Provenance
              map={map}
              papers={papers}
              selection={selected}
              onShowReasoning={busy ? undefined : () => setTab("reasoning")}
            />
          </Inspector>
        </main>
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

type Tab = "map" | "reasoning";
interface Live {
  runId: string;
  base: MapResult | null; // null while a new map is being built
  papers: Paper[];
  question: string;
  title: string;
  keepCurrentGraph?: boolean;
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
    <main
      className={`workspace-grid live-build${panels.className}`}
      style={panels.style}
    >
      <aside className="topic-sidebar">
        <h2>{live.title}</h2>
        <p className="muted small">{live.question}</p>
        <p className="small">
          {live.papers.length} papers are being grouped and named.
        </p>
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
      />
      <PanelHandle side="right" panels={panels.panels} set={panels.set} />
      <aside className="inspector">
        {paper ? (
          <>
            <h3 className="paper-title">{paper.title}</h3>
            <p className="paper-meta">
              {paper.year ?? "Year unknown"} · {paper.source}
            </p>
            <p className="small">{paper.abstract}</p>
          </>
        ) : (
          <p className="muted">
            The map is being built; click a paper to read its abstract
            meanwhile.
          </p>
        )}
      </aside>
    </main>
  );
}
