"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import {
  GitBranch,
  Play,
  CheckCircle2,
  Clock,
  AlertTriangle,
  ArrowRight,
  ShieldCheck,
  Cpu,
  Database,
  UserCheck,
  Zap,
  Sparkles,
  Plus,
  FolderOpen,
  Loader2,
  TerminalSquare,
  X,
} from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Input } from "@/components/ui/Input";
import {
  orgApi,
  workspaceApi,
  workflowApi,
  type Organization,
  type Workspace,
  type Workflow,
  type WorkflowRun,
  type WorkflowStepResult,
  type WorkflowTemplate,
} from "@/lib/api";

const STEP_ICONS: Record<string, React.ReactNode> = {
  trigger: <Zap className="h-4 w-4 text-amber-500" />,
  agent: <Cpu className="h-4 w-4 text-blue-500" />,
  vector_db: <Database className="h-4 w-4 text-purple-500" />,
  automated_compliance_check: <UserCheck className="h-4 w-4 text-emerald-500" />,
  action: <ShieldCheck className="h-4 w-4 text-indigo-500" />,
};

function statusBadge(status: string) {
  switch (status.toUpperCase()) {
    case "COMPLETED":
    case "INDEXED":
      return <Badge variant="success">{status}</Badge>;
    case "FAILED":
      return <Badge variant="error">{status}</Badge>;
    case "RUNNING":
    case "PROCESSING":
    case "PENDING":
      return <Badge variant="warning">{status}</Badge>;
    default:
      return <Badge variant="default">{status}</Badge>;
  }
}

export default function WorkflowsPage() {
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWs, setSelectedWs] = useState<string>("");
  const [loadingWs, setLoadingWs] = useState(true);

  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [wfTotal, setWfTotal] = useState(0);
  const [wfPage, setWfPage] = useState(1);
  const [loadingWorkflows, setLoadingWorkflows] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  // Create & run dialog
  const [creatingTemplate, setCreatingTemplate] = useState<WorkflowTemplate | null>(null);
  const [wfName, setWfName] = useState("");
  const [wfDesc, setWfDesc] = useState("");
  const [wfQuery, setWfQuery] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  // Active run visualization
  const [activeRun, setActiveRun] = useState<WorkflowRun | null>(null);
  const [activeWorkflow, setActiveWorkflow] = useState<Workflow | null>(null);
  const [runHistory, setRunHistory] = useState<WorkflowRun[]>([]);
  const [polling, setPolling] = useState(false);
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  // Bootstrap: orgs -> workspaces
  useEffect(() => {
    orgApi
      .list()
      .then((data) => {
        setOrgs(data.items);
        if (data.items.length > 0) {
          return workspaceApi.list(data.items[0].id);
        }
        return Promise.resolve({
          items: [] as Workspace[],
          total: 0,
          page: 1,
          page_size: 25,
          pages: 0,
        });
      })
      .then((wss) => {
        setWorkspaces(wss.items);
        if (wss.items.length > 0) setSelectedWs(wss.items[0].id);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoadingWs(false));
  }, []);

  // Load templates once
  useEffect(() => {
    workflowApi.listTemplates().then(setTemplates).catch((e) => setError(e.message));
  }, []);

  // Load workflows when workspace changes
  useEffect(() => {
    if (!selectedWs) return;
    setLoadingWorkflows(true);
    workflowApi
      .list(selectedWs)
      .then((data) => {
        setWorkflows(data.items);
        setWfTotal(data.total);
        setWfPage(data.page);
        if (data.items.length > 0) {
          setActiveWorkflow(data.items[0]);
          loadLatestRun(data.items[0].id);
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoadingWorkflows(false));
  }, [selectedWs]);

  async function loadMoreWorkflows() {
    if (loadingMore || !selectedWs) return;
    setLoadingMore(true);
    try {
      const data = await workflowApi.list(selectedWs, wfPage + 1);
      setWorkflows((prev) => [...prev, ...data.items]);
      setWfTotal(data.total);
      setWfPage(data.page);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load more workflows");
    } finally {
      setLoadingMore(false);
    }
  }

  // Poll active run while it is pending/running
  useEffect(() => {
    return () => {
      if (pollTimer.current) clearInterval(pollTimer.current);
    };
  }, []);

  async function loadLatestRun(workflowId: string) {
    try {
      const runs = await workflowApi.listRuns(workflowId);
      setRunHistory(runs.items);
      if (runs.items.length > 0) setActiveRun(runs.items[0]);
    } catch {
      // ignore
    }
  }

  function startPolling(run: WorkflowRun) {
    if (pollTimer.current) clearInterval(pollTimer.current);
    pollTimer.current = setInterval(async () => {
      try {
        const latest = await workflowApi.listRuns(run.workflow_id);
        setRunHistory(latest.items);
        if (latest.items.length > 0) setActiveRun(latest.items[0]);
        const newest = latest.items[0];
        if (newest && (newest.status === "COMPLETED" || newest.status === "FAILED")) {
          if (pollTimer.current) clearInterval(pollTimer.current);
          setPolling(false);
        }
      } catch {
        if (pollTimer.current) clearInterval(pollTimer.current);
        setPolling(false);
      }
    }, 2000);
    setPolling(true);
  }

  async function handleCreateAndRun(e: FormEvent) {
    e.preventDefault();
    if (!creatingTemplate || !selectedWs) return;
    setSubmitting(true);
    setError("");
    try {
      const wf = await workflowApi.create({
        name: wfName || creatingTemplate.title,
        description: wfDesc || creatingTemplate.description,
        template_id: creatingTemplate.id,
        workspace_id: selectedWs,
      });
      const run = await workflowApi.run(wf.id, creatingTemplate.id === "support-router" ? wfQuery : undefined);
      setWorkflows((prev) => [wf, ...prev.filter((w) => w.id !== wf.id)]);
      setActiveWorkflow(wf);
      setActiveRun(run);
      setRunHistory((prev) => [run, ...prev]);
      setCreatingTemplate(null);
      setWfName("");
      setWfDesc("");
      setWfQuery("");
      startPolling(run);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create workflow");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRunExisting(wf: Workflow) {
    setError("");
    setActiveWorkflow(wf);
    try {
      const run = await workflowApi.run(wf.id, wf.template_id === "support-router" ? wfQuery : undefined);
      setActiveRun(run);
      setRunHistory((prev) => [run, ...prev]);
      startPolling(run);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to run workflow");
    }
  }

  function selectRun(run: WorkflowRun) {
    setActiveRun(run);
    const wf = workflows.find((w) => w.id === run.workflow_id);
    if (wf) setActiveWorkflow(wf);
  }

  if (loadingWs) {
    return (
      <div className="flex items-center justify-center py-24">
        <p className="text-[var(--muted-foreground)]">Loading workspaces...</p>
      </div>
    );
  }

  if (orgs.length === 0 || workspaces.length === 0) {
    return (
      <div className="mx-auto max-w-xl space-y-6 py-16 text-center">
        <FolderOpen className="mx-auto h-12 w-12 text-[var(--muted-foreground)]" />
        <h1 className="text-2xl font-bold">Workflows & Automation</h1>
        <p className="text-sm text-[var(--muted-foreground)]">
          Create an organization and workspace first, then build agentic automation
          pipelines against your knowledge base.
        </p>
        <a href="/dashboard">
          <Button>
            <Plus className="h-4 w-4" />
            Go to Dashboard
          </Button>
        </a>
      </div>
    );
  }

  const runningStep = (step: WorkflowStepResult, idx: number) => (
    <div key={step.id} className="relative">
      <div
        className={`rounded-xl border p-4 transition ${
          step.status === "running"
            ? "border-[var(--primary)] bg-[var(--primary)]/10 ring-2 ring-[var(--primary)]/30"
            : step.status === "completed"
            ? "border-emerald-500/40 bg-emerald-500/5"
            : step.status === "failed"
            ? "border-red-500/50 bg-red-500/5"
            : "border-[var(--border)] bg-[var(--card)]"
        }`}
      >
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold text-[var(--muted-foreground)]">
            Step 0{idx + 1}
          </span>
          {STEP_ICONS[step.type] || <Cpu className="h-4 w-4 text-blue-500" />}
        </div>
        <h4 className="font-medium text-sm mb-1">{step.name}</h4>
        <p className="text-xs text-[var(--muted-foreground)] mb-3 line-clamp-2">{step.output}</p>
        <div className="flex items-center justify-between text-xs">
          <span className="capitalize text-[var(--muted-foreground)]">{step.type.replace("_", " ")}</span>
          {step.duration_ms != null && (
            <span className="font-mono text-[var(--muted-foreground)]">{(step.duration_ms / 1000).toFixed(2)}s</span>
          )}
        </div>
      </div>
      {idx < (activeRun?.steps?.length ?? 0) - 1 && (
        <ArrowRight className="hidden md:block absolute -right-3 top-1/2 -translate-y-1/2 h-5 w-5 text-[var(--muted-foreground)] z-10" />
      )}
    </div>
  );

  const stepStatus = (s: WorkflowStepResult): "idle" | "running" | "completed" | "failed" =>
    s.status || "idle";

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <GitBranch className="h-6 w-6 text-[var(--primary)]" />
            Agentic Workflows & Automation
          </h1>
          <p className="text-sm text-[var(--muted-foreground)]">
            Real pipelines backed by your document ingestion, Qdrant, and compliance infrastructure
          </p>
        </div>
        <select
          value={selectedWs}
          onChange={(e) => setSelectedWs(e.target.value)}
          className="rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm"
        >
          {workspaces.map((ws) => (
            <option key={ws.id} value={ws.id}>
              {ws.name}
            </option>
          ))}
        </select>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-400">
          {error}
        </div>
      )}

      {/* Templates */}
      <section>
        <h2 className="mb-3 text-lg font-semibold flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-amber-500" />
          Workflow Templates
        </h2>
        <div className="grid gap-4 md:grid-cols-3">
          {templates.map((tmpl) => (
            <Card
              key={tmpl.id}
              className="flex flex-col transition hover:border-[var(--primary)] hover:shadow-md"
            >
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <Badge variant="info">{tmpl.category}</Badge>
                  <span className="text-xs text-[var(--muted-foreground)]">{tmpl.steps.length} steps</span>
                </div>
                <h3 className="font-semibold pt-2 text-sm">{tmpl.title}</h3>
              </CardHeader>
              <CardContent className="flex flex-1 flex-col gap-3">
                <p className="text-xs text-[var(--muted-foreground)] flex-1">{tmpl.description}</p>
                <div className="flex flex-wrap gap-1.5">
                  {tmpl.steps.map((s) => (
                    <span
                      key={s.id}
                      className="inline-flex items-center gap-1 rounded-md bg-[var(--muted)] px-2 py-0.5 text-[10px] font-medium text-[var(--muted-foreground)]"
                    >
                      {STEP_ICONS[s.type]}
                      {s.name}
                    </span>
                  ))}
                </div>
                <Button
                  size="sm"
                  onClick={() => {
                    setCreatingTemplate(tmpl);
                    setWfName(tmpl.title);
                    setWfDesc("");
                    setWfQuery("");
                    setError("");
                  }}
                >
                  <Plus className="h-4 w-4" />
                  Create & Run
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      {/* Create & Run dialog */}
      {creatingTemplate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <Card className="w-full max-w-md">
            <CardHeader>
              <div className="flex items-center justify-between">
                <h2 className="font-semibold">Create & Run Workflow</h2>
                <button
                  className="rounded p-1 hover:bg-[var(--muted)]"
                  onClick={() => setCreatingTemplate(null)}
                  aria-label="Close"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleCreateAndRun} className="space-y-4">
                <p className="text-xs text-[var(--muted-foreground)]">{creatingTemplate.description}</p>
                <Input label="Workflow Name" id="wf-name" value={wfName} onChange={(e) => setWfName(e.target.value)} required />
                <Input label="Description (optional)" id="wf-desc" value={wfDesc} onChange={(e) => setWfDesc(e.target.value)} />
                {creatingTemplate.id === "support-router" && (
                  <Input
                    label="Sample Support Query"
                    id="wf-query"
                    value={wfQuery}
                    onChange={(e) => setWfQuery(e.target.value)}
                    placeholder="e.g. How do I reset my account password?"
                  />
                )}
                <div className="flex gap-2 pt-2">
                  <Button type="submit" disabled={submitting}>
                    {submitting ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Starting...
                      </>
                    ) : (
                      <>
                        <Play className="h-4 w-4" />
                        Create & Execute
                      </>
                    )}
                  </Button>
                  <Button type="button" variant="secondary" onClick={() => setCreatingTemplate(null)}>
                    Cancel
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Your workflows */}
      <section>
        <h2 className="mb-3 text-lg font-semibold">Your Workflows</h2>
        {loadingWorkflows ? (
          <p className="text-sm text-[var(--muted-foreground)]">Loading workflows...</p>
        ) : workflows.length === 0 ? (
          <Card>
            <CardContent className="py-10 text-center">
              <GitBranch className="mx-auto mb-3 h-10 w-10 text-[var(--muted-foreground)]" />
              <p className="text-[var(--muted-foreground)]">
                No workflows yet. Pick a template above to create and execute your first automation.
              </p>
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardContent className="divide-y divide-[var(--border)] p-0">
              {workflows.map((wf) => {
                const latest = runHistory.find((r) => r.workflow_id === wf.id);
                return (
                  <div
                    key={wf.id}
                    className={`flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between ${
                      activeWorkflow?.id === wf.id ? "bg-[var(--primary)]/5" : ""
                    }`}
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <h3 className="font-medium text-sm truncate">{wf.name}</h3>
                        {statusBadge(wf.status)}
                      </div>
                      <p className="text-xs text-[var(--muted-foreground)] truncate mt-0.5">
                        {templates.find((t) => t.id === wf.template_id)?.title || wf.template_id}
                      </p>
                      {latest && (
                        <p className="text-[11px] text-[var(--muted-foreground)] mt-1">
                          Last run: {latest.status}
                          {latest.completed_at
                            ? ` · ${new Date(latest.completed_at).toLocaleTimeString()}`
                            : ""}
                        </p>
                      )}
                    </div>
                    <div className="flex shrink-0 gap-2">
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => {
                          setActiveWorkflow(wf);
                          setWfQuery("");
                          loadLatestRun(wf.id);
                        }}
                      >
                        <GitBranch className="h-4 w-4" />
                        View
                      </Button>
                      <Button size="sm" onClick={() => handleRunExisting(wf)} disabled={polling}>
                        <Play className="h-4 w-4" />
                        Run
                      </Button>
                    </div>
                  </div>
                );
              })}
            </CardContent>
          </Card>
        )}
        {workflows.length > 0 && workflows.length < wfTotal && (
          <div className="flex justify-center pt-2">
            <Button variant="secondary" size="sm" onClick={loadMoreWorkflows} disabled={loadingMore}>
              {loadingMore ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <FolderOpen className="h-4 w-4" />
              )}
              Load More ({workflows.length} of {wfTotal})
            </Button>
          </div>
        )}
      </section>

      {/* Run visualization */}
      {activeRun && activeWorkflow && (
        <Card>
          <CardHeader>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-2">
                <Sparkles className="h-5 w-5 text-[var(--primary)]" />
                <h2 className="font-semibold text-base">
                  Pipeline Run — {activeWorkflow.name}
                </h2>
                {statusBadge(activeRun.status)}
              </div>
              <div className="flex items-center gap-1 rounded-lg border border-[var(--border)] bg-[var(--card)] p-1">
                {runHistory.slice(0, 6).map((r) => (
                  <button
                    key={r.id}
                    onClick={() => selectRun(r)}
                    title={`Run ${r.status}`}
                    className={`h-6 w-6 rounded-md text-[10px] font-bold transition ${
                      activeRun.id === r.id
                        ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                        : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
                    }`}
                  >
                    {r.status === "COMPLETED" ? "✓" : r.status === "FAILED" ? "✗" : "…"}
                  </button>
                ))}
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="grid gap-4 md:grid-cols-4">
              {(activeRun.steps ?? []).map((st, idx) => runningStep({ ...st, status: stepStatus(st) }, idx))}
              {activeRun.steps && activeRun.steps.length === 0 && (
                <p className="col-span-4 text-sm text-[var(--muted-foreground)]">
                  Run has not produced steps yet — pipeline is starting.
                </p>
              )}
            </div>

            {/* Execution terminal */}
            <div className="rounded-xl border border-slate-800 bg-slate-950 p-4 font-mono text-xs text-slate-200">
              <div className="flex items-center justify-between mb-2 pb-2 border-b border-slate-800 text-slate-400">
                <span className="flex items-center gap-2">
                  <TerminalSquare className="h-4 w-4" />
                  Execution Output Terminal
                </span>
                {polling && (
                  <span className="flex items-center gap-1 text-[10px] uppercase text-blue-400">
                    <Clock className="h-3 w-3 animate-spin" /> Live
                  </span>
                )}
              </div>
              <div className="space-y-1 max-h-56 overflow-y-auto">
                {(!activeRun.logs || activeRun.logs.length === 0) && activeRun.status === "PENDING" && (
                  <p className="text-slate-500 italic">Run enqueued — awaiting worker...</p>
                )}
                {(!activeRun.logs || activeRun.logs.length === 0) && activeRun.status === "RUNNING" && (
                  <p className="text-slate-500 italic">Pipeline executing in the background...</p>
                )}
                {(!activeRun.logs || activeRun.logs.length === 0) && activeRun.status === "COMPLETED" && (
                  <p className="text-slate-500 italic">Run completed with no logged output.</p>
                )}
                {activeRun.logs?.map((log, i) => (
                  <p
                    key={i}
                    className={
                      log.level === "success"
                        ? "text-emerald-400"
                        : log.level === "error"
                        ? "text-red-400"
                        : log.level === "warn"
                        ? "text-amber-400"
                        : "text-blue-400"
                    }
                  >
                    [{new Date(log.ts).toLocaleTimeString()}] {log.message}
                  </p>
                ))}
              </div>
            </div>

            {activeRun.status === "FAILED" && activeRun.error && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-400">
                <span className="flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4" />
                  {activeRun.error}
                </span>
              </div>
            )}

            {/* Step data details for completed runs */}
            {(activeRun.steps ?? []).some((s) => s.data && Object.keys(s.data).length > 0) && (
              <div className="grid gap-3 md:grid-cols-2">
                {(activeRun.steps ?? [])
                  .filter((s) => s.data && Object.keys(s.data).length > 0)
                  .map((s) => (
                    <div key={s.id} className="rounded-xl border border-[var(--border)] p-4">
                      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                        {s.name} — Results
                      </p>
                      <pre className="whitespace-pre-wrap break-all text-xs text-[var(--foreground)]">
                        {JSON.stringify(s.data, null, 2)}
                      </pre>
                    </div>
                  ))}
              </div>
            )}

            {activeRun.status === "COMPLETED" && (
              <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-400">
                <CheckCircle2 className="h-4 w-4" />
                Workflow executed successfully against real infrastructure.
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
