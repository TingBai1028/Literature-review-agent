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
    void operate("正在建立地图", async () => {
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
        title: "正在建立地图",
      });
      try {
        const map = await request<MapResult>("/cluster", {
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
        await ws.open(map.run_id);
      } finally {
        setLive(null);
      }
    });
  // Spec F5: swap the side papers for the next-best backup papers; main and foundation stay.
  const refresh = () =>
    data &&
    void operate("正在换一批论文", async () => {
      const runId = newRunId();
      setLive({
        runId,
        base: data.map,
        papers: data.papers,
        question: data.map.question,
        title: "换一批论文",
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
        `已换入 ${map.refresh?.swapped_in.length ?? 0} 篇备选论文，主簇和基础簇保持不变。` +
          (map.analysis ? "关联和研究空白需要重新运行分析。" : ""),
      );
    });
  // Spec E: Graph 1 (paper edges) is opened as soon as it is ready; Graph 2 (gaps) follows on that version.
  const runStage = (map: MapResult, stage: "connections" | "gaps") => {
    const runId = newRunId();
    setLive({
      runId,
      base: map,
      papers: data?.papers ?? [],
      question: map.question,
      title:
        stage === "connections" ? "图 1：寻找论文关联" : "图 2：寻找研究空白",
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
  const analyze = () =>
    data &&
    void operate("正在寻找论文关联（图 1）", async () => {
      let map = data.map;
      if (!map.analysis?.completed_stages?.includes("connections")) {
        map = await runStage(map, "connections");
        await ws.open(map.run_id);
        if (map.status === "partial") {
          setNotice(
            "已保留完成结果。原版本保持为当前版本，可打开这个待完成版本继续分析。",
          );
          return;
        }
      }
      setBusy("图 1 已可浏览，正在寻找研究空白（图 2）");
      map = await runStage(map, "gaps");
      await ws.open(map.run_id);
      setNotice(
        map.status === "partial"
          ? "图 1 已保留；图 2 未完成，可再次运行分析继续。"
          : "图 2（研究空白）已生成，切换到“图 2 · 研究空白”查看。",
      );
    });
  return (
    <DialogNotice.Provider value={notice}>
      <div className="app-shell">
        <header className="app-header">
          <a className="wordmark" href="/">
            Literature Map
          </a>
          <nav className="top-nav" aria-label="主导航">
            <button
              className={tab === "map" ? "active" : ""}
              aria-pressed={tab === "map"}
              onClick={() => setTab("map")}
            >
              论文地图
            </button>
            <button
              className={tab === "review" ? "active" : ""}
              aria-pressed={tab === "review"}
              onClick={() => setTab("review")}
              disabled={!data}
            >
              人工验收
            </button>
            <button
              className={tab === "reasoning" ? "active" : ""}
              aria-pressed={tab === "reasoning"}
              onClick={() => setTab("reasoning")}
              disabled={!data}
            >
              推理过程
            </button>
          </nav>
          <div className="header-actions">
            <button
              className="text-button history-button"
              onClick={() => setDialog("versions")}
              disabled={!data || !!busy}
            >
              版本记录
            </button>
            <button
              className="text-button"
              onClick={refresh}
              disabled={
                !data || !!busy || !editable || !data.map.backup_pool_size
              }
              title="把侧簇论文换成备选池中排名靠前的论文；主簇和基础簇不变"
            >
              换一批论文
              {data?.map.backup_pool_size
                ? ` · 备选 ${data.map.backup_pool_size}`
                : ""}
            </button>
            <button
              className="primary-button analyze-button"
              disabled={
                !data ||
                !!busy ||
                data.map.sample_mode !== ws.config.sample_mode ||
                (!editable && data.map.status !== "partial")
              }
              onClick={analyze}
            >
              {busy ? <LoaderCircle size={16} className="spin" /> : null}
              {busy
                ? "处理中…"
                : data?.map.status === "partial"
                  ? "继续分析"
                  : "运行分析"}
            </button>
          </div>
        </header>
        {data && (
          <section className="question-bar">
            <h1 title={data.map.question}>{data.map.question}</h1>
            <span className="map-counts">
              {data.papers.length} 篇论文 ·{" "}
              {data.map.clusters.filter((c) => c.kind === "main").length} 个主簇
              ·{" "}
              {data.map.clusters.filter((c) => c.kind === "foundation").length}{" "}
              个基础簇 ·{" "}
              {
                data.map.clusters.filter(
                  (c) => c.kind !== "main" && c.kind !== "foundation",
                ).length
              }{" "}
              个侧簇
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
                ? "样例模式：分组、相似度和评分为占位结果。"
                : "当前服务为样例模式；真实地图可阅读，切换真实模式后可执行分析或移动。")}
            {notice && (
              <button
                className="icon-button"
                aria-label="关闭提示"
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
            <p>正在读取地图与原文…</p>
          </main>
        ) : !data ? (
          <main className="empty-workspace">
            <h1>从论文出发，连接研究问题。</h1>
            <p>输入研究问题检索论文，审核后建立可查看原文证据的研究地图。</p>
            <button className="primary-button" onClick={() => setDialog("new")}>
              新建地图
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
            onNew={() => setDialog("new")}
            onOperation={operate}
            onOpen={ws.open}
            timeout={(ws.config.run_timeout_s + 120) * 1000}
            live={live?.base ? { ...live, events } : null}
          />
        )}
        {data && (
          <footer className="workspace-footer">
            <div className="version-selector">
              <strong>当前视图</strong>
              <label>
                <span className="sr-only">选择地图版本</span>
                <select
                  value={ws.runId}
                  disabled={!!busy}
                  onChange={(e) => ws.setRunId(e.target.value)}
                >
                  {ws.catalog.map((m) => (
                    <option value={m.run_id} key={m.run_id}>
                      {m.sample_mode ? "样例 · " : ""}v{m.revision}{" "}
                      {m.active ? "· 当前 " : ""}· {m.run_id}
                    </option>
                  ))}
                </select>
                <ChevronDown size={13} />
              </label>
            </div>
            {data.map.warnings.length > 0 && (
              <details className="quality-notes">
                <summary>质量提示 {data.map.warnings.length}</summary>
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
              void operate("正在刷新版本", async () => {
                await ws.open(data.map.run_id);
              })
            }
            onView={(id) => {
              setDialog(null);
              void ws.open(id);
            }}
            onActivate={(id) =>
              void operate("正在切换当前版本", async () => {
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
  onNew,
  onOperation,
  onOpen,
  timeout,
  live,
}: {
  data: NonNullable<ReturnType<typeof useWorkspace>["data"]>;
  tab: Tab;
  setTab: (v: Tab) => void;
  editable: boolean;
  busy: boolean;
  onNew: () => void;
  onOperation: (label: string, action: () => Promise<void>) => Promise<void>;
  onOpen: (id: string) => Promise<void>;
  timeout: number;
  live: (Live & { events: RunEvent[] }) | null;
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
    if (f === "main_side")
      setSelection({
        type: "paper",
        id:
          map.clusters.find((c) => c.kind === "main")?.paper_ids[0] ??
          papers[0].id,
      });
  };
  return (
    <>
      {tab === "review" ? (
        <ReviewPanel map={map} timeout={timeout} />
      ) : tab === "reasoning" ? (
        <ReasoningPanel
          map={data.map}
          versions={data.versions}
          live={live?.events ?? []}
        />
      ) : (
        <main className="workspace-grid">
          <button
            className="mobile-topic-toggle"
            onClick={() => setMobile((v) => !v)}
            aria-label="切换主题导航"
          >
            <Menu size={17} />
            研究主题
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
            onNew={onNew}
            mobileOpen={mobile}
          />
          <LiteratureGraph
            map={map}
            papers={papers}
            selection={selection}
            onSelect={setSelection}
            filter={filter}
            onFilter={changeFilter}
            search={search}
            onReview={() => setTab("review")}
          />
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
          >
            <Provenance
              map={map}
              papers={papers}
              selection={selection}
              onShowReasoning={() => setTab("reasoning")}
            />
          </Inspector>
          {live && (
            <ActivityFeed
              events={live.events}
              title={live.title}
              onShowAll={() => setTab("reasoning")}
            />
          )}
        </main>
      )}
      {tab === "map" && (
        <div className="move-bar">
          {moves.length > 0 && (
            <>
              <span>{moves.length} 篇论文待移动</span>
              <button
                className="text-button small"
                disabled={busy}
                onClick={() => setMoves([])}
              >
                清空
              </button>
            </>
          )}
          <button
            className="secondary-button"
            disabled={!moves.length || busy || !editable}
            onClick={() =>
              void onOperation("正在检查移动约束", async () =>
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
            预览移动
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
            void onOperation("正在生成新版本", async () => {
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
  const paper = live.papers.find(
    (p) => selection?.type === "paper" && p.id === selection.id,
  );
  return (
    <main className="workspace-grid live-build">
      <aside className="topic-sidebar">
        <h2>{live.title}</h2>
        <p className="muted small">{live.question}</p>
        <p className="small">{live.papers.length} 篇论文正在分组和命名。</p>
      </aside>
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
      <aside className="inspector">
        {paper ? (
          <>
            <h3 className="paper-title">{paper.title}</h3>
            <p className="paper-meta">
              {paper.year ?? "年份未知"} · {paper.source}
            </p>
            <p className="small">{paper.abstract}</p>
          </>
        ) : (
          <p className="muted">地图生成中，可以先点击论文查看摘要。</p>
        )}
      </aside>
      <ActivityFeed events={events} title={live.title} />
    </main>
  );
}
