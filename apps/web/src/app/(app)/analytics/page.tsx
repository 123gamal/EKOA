"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import {
  BarChart3,
  Cpu,
  Database,
  FileText,
  FolderKanban,
  Loader2,
  ShieldCheck,
  Activity,
  AlertTriangle,
  Building2,
  GitBranch,
  Gauge,
  Timer,
  DollarSign,
  ShieldAlert,
  CheckCircle2,
} from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { analyticsApi } from "@/lib/api";

const PAGE_SIZE = 25;

function MetricCard({
  title,
  value,
  sub,
  icon,
}: {
  title: string;
  value: string;
  sub: string;
  icon: React.ReactNode;
}) {
  return (
    <Card className="hover:shadow-md transition">
      <CardContent className="p-5">
        <div className="flex items-center justify-between">
          <p className="text-xs font-medium text-[var(--muted-foreground)]">{title}</p>
          <div className="rounded-lg p-2 text-white shadow-sm bg-gradient-to-br from-blue-500 to-indigo-600">
            {icon}
          </div>
        </div>
        <div className="mt-3">
          <h3 className="text-2xl font-bold tracking-tight">{value}</h3>
          <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">{sub}</p>
        </div>
      </CardContent>
    </Card>
  );
}

function barColor(status: string) {
  switch (status.toUpperCase()) {
    case "INDEXED":
      return "bg-gradient-to-r from-emerald-400 to-emerald-600";
    case "FAILED":
      return "bg-gradient-to-r from-red-400 to-red-600";
    case "PROCESSING":
      return "bg-gradient-to-r from-amber-400 to-amber-600";
    case "PENDING":
      return "bg-gradient-to-r from-blue-400 to-blue-600";
    default:
      return "bg-[var(--muted)]";
  }
}

function actionLabel(action: string) {
  const map: Record<string, string> = {
    "document.upload": "Document Uploaded",
    "workflow.run": "Workflow Executed",
    "workflow.compliance_audit": "Compliance Audit",
    "organization.create": "Organization Created",
    "workspace.create": "Workspace Created",
  };
  return map[action] || action;
}

export default function AnalyticsPage() {
  const overviewQuery = useQuery({
    queryKey: ["analytics-overview"],
    queryFn: () => analyticsApi.overview(),
  });
  const overview = overviewQuery.data ?? null;

  const docsQuery = useInfiniteQuery({
    queryKey: ["analytics-documents"],
    queryFn: ({ pageParam }) => analyticsApi.documents(pageParam, PAGE_SIZE),
    initialPageParam: 1,
    getNextPageParam: (lastPage) =>
      lastPage.page < lastPage.pages ? lastPage.page + 1 : undefined,
  });
  const docRows =
    docsQuery.data?.pages.flatMap((p) => p.items) ??
    [];
  const docTotal = docsQuery.data?.pages[0]?.total ?? 0;

  const modelPerfQuery = useQuery({
    queryKey: ["analytics-model-performance"],
    queryFn: () => analyticsApi.modelPerformance(7),
  });
  const perf = modelPerfQuery.data ?? null;

  if (overviewQuery.isLoading) {
    return (
      <div className="flex items-center justify-center py-24 gap-2">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--primary)]" />
        <p className="text-[var(--muted-foreground)]">Loading live analytics...</p>
      </div>
    );
  }

  if (overviewQuery.isError || !overview) {
    return (
      <div className="mx-auto max-w-md space-y-4 py-16 text-center">
        <AlertTriangle className="mx-auto h-10 w-10 text-red-500" />
        <h1 className="text-xl font-bold">Analytics Unavailable</h1>
        <p className="text-sm text-[var(--muted-foreground)]">
          {overviewQuery.error instanceof Error ? overviewQuery.error.message : "Could not load analytics"}
        </p>
      </div>
    );
  }

  const byStatus = overview.documents_by_status;
  const totalDocs = overview.documents || 0;
  const maxDay = Math.max(1, ...overview.uploads_last_7_days.map((d) => d.count));
  const runByStatus = overview.workflow_runs;
  const totalRuns = Object.values(runByStatus).reduce((a, b) => a + b, 0);

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
          <BarChart3 className="h-6 w-6 text-[var(--primary)]" />
          AI Observability & Analytics
        </h1>
        <p className="text-sm text-[var(--muted-foreground)]">
          Live operational metrics derived from your documents, vector index, and workflow runs
        </p>
      </div>

      {/* KPI Cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          title="Documents Ingested"
          value={totalDocs.toLocaleString()}
          sub={`${(byStatus.INDEXED || 0).toLocaleString()} indexed`}
          icon={<FileText className="h-5 w-5" />}
        />
        <MetricCard
          title="Vector Chunks Indexed"
          value={overview.chunks.toLocaleString()}
          sub="stored in Qdrant"
          icon={<Database className="h-5 w-5" />}
        />
        <MetricCard
          title="Processing Success Rate"
          value={totalDocs ? `${(overview.success_rate * 100).toFixed(1)}%` : "—"}
          sub={`${byStatus.FAILED || 0} failed`}
          icon={<ShieldCheck className="h-5 w-5" />}
        />
        <MetricCard
          title="Workflow Runs"
          value={totalRuns.toLocaleString()}
          sub={`${runByStatus.COMPLETED || 0} completed`}
          icon={<GitBranch className="h-5 w-5" />}
        />
      </div>

      {/* Model Performance (computed from ai_call_logs telemetry — real data) */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold tracking-tight flex items-center gap-2">
            <Gauge className="h-5 w-5 text-violet-500" />
            Model Performance
          </h2>
          {modelPerfQuery.isLoading ? (
            <Loader2 className="h-4 w-4 animate-spin text-[var(--muted-foreground)]" />
          ) : (
            <Badge variant="info">
              {perf?.summary.calls ?? 0} calls tracked
            </Badge>
          )}
        </div>

        {modelPerfQuery.isError ? (
          <Card>
            <CardContent className="flex items-center gap-2 p-5 text-sm text-[var(--muted-foreground)]">
              <AlertTriangle className="h-4 w-4 text-red-500" />
              {modelPerfQuery.error instanceof Error
                ? modelPerfQuery.error.message
                : "Could not load model performance"}
            </CardContent>
          </Card>
        ) : (
          <>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <MetricCard
                title="Avg LLM Latency"
                value={perf?.summary.avg_latency_ms != null ? `${perf.summary.avg_latency_ms.toFixed(0)} ms` : "—"}
                sub={perf?.summary.p95_latency_ms != null ? `p95: ${perf.summary.p95_latency_ms.toFixed(0)} ms` : "no data yet"}
                icon={<Timer className="h-5 w-5" />}
              />
              <MetricCard
                title="Tokens"
                value={(perf?.summary.total_tokens ?? 0).toLocaleString()}
                sub={`${(perf?.summary.prompt_tokens ?? 0).toLocaleString()} prompt · ${(perf?.summary.completion_tokens ?? 0).toLocaleString()} completion`}
                icon={<Database className="h-5 w-5" />}
              />
              <MetricCard
                title="Degraded Rate"
                value={`${((perf?.summary.degraded_rate ?? 0) * 100).toFixed(1)}%`}
                sub="fallback template used"
                icon={<AlertTriangle className="h-5 w-5" />}
              />
              <MetricCard
                title="Guardrail Trigger Rate"
                value={`${((perf?.summary.guardrail_trigger_rate ?? 0) * 100).toFixed(1)}%`}
                sub="input heuristic flagged"
                icon={<ShieldAlert className="h-5 w-5" />}
              />
              <MetricCard
                title="Citation Drop Rate"
                value={`${((perf?.summary.citation_drop_rate ?? 0) * 100).toFixed(1)}%`}
                sub="unverified citations dropped"
                icon={<CheckCircle2 className="h-5 w-5" />}
              />
              <MetricCard
                title="Est. Cost"
                value={perf?.summary.est_cost_usd ? `$${perf.summary.est_cost_usd.toFixed(4)}` : "$0.00"}
                sub={perf?.summary.calls ? `${perf.summary.calls} calls` : "no data yet"}
                icon={<DollarSign className="h-5 w-5" />}
              />
            </div>

            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold text-base flex items-center gap-2">
                    <Activity className="h-5 w-5 text-violet-500" />
                    Daily Token Usage — last 7 days
                  </h3>
                  <span className="text-[11px] text-[var(--muted-foreground)]">
                    {(perf?.daily ?? []).some((d) => d.calls > 0) ? "Real telemetry" : "No calls yet"}
                  </span>
                </div>
              </CardHeader>
              <CardContent>
                <div className="flex h-40 items-end justify-between gap-2">
                  {(perf?.daily ?? []).map((d) => {
                    const max = Math.max(1, ...(perf?.daily ?? []).map((x) => x.total_tokens));
                    return (
                      <div key={d.date} className="flex flex-1 flex-col items-center gap-1">
                        <span className="text-[10px] font-mono text-[var(--muted-foreground)]">
                          {d.calls > 0 ? d.total_tokens : ""}
                        </span>
                        <div
                          className="w-full max-w-10 rounded-t-md bg-gradient-to-t from-violet-600 to-fuchsia-400 transition-all"
                          style={{ height: `${d.calls > 0 ? Math.max(6, (d.total_tokens / max) * 100) : 4}px` }}
                        />
                        <span className="text-[10px] text-[var(--muted-foreground)]">
                          {new Date(d.date).toLocaleDateString(undefined, { weekday: "short" })}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold text-base">Recent AI Calls</h3>
                  {perf?.summary.calls ? (
                    <span className="text-xs text-[var(--muted-foreground)]">
                      providers:{" "}
                      {Object.entries(perf.summary.providers)
                        .map(([p, n]) => `${p}: ${n}`)
                        .join(" · ")}
                    </span>
                  ) : null}
                </div>
              </CardHeader>
              <CardContent>
                {!perf?.recent_calls.items.length ? (
                  <p className="py-4 text-center text-sm text-[var(--muted-foreground)]">
                    No AI calls recorded yet. Ask a question in Chat to populate model performance.
                  </p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-sm">
                      <thead className="border-b border-[var(--border)] text-xs text-[var(--muted-foreground)] uppercase">
                        <tr>
                          <th className="py-3 px-2">Provider / Model</th>
                          <th className="py-3 px-2">Latency</th>
                          <th className="py-3 px-2">Tokens</th>
                          <th className="py-3 px-2">Flags</th>
                          <th className="py-3 px-2">Est. Cost</th>
                          <th className="py-3 px-2">Time</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[var(--border)]">
                        {perf.recent_calls.items.map((c) => (
                          <tr key={c.id} className="hover:bg-[var(--muted)]/50 transition">
                            <td className="py-3 px-2 font-medium">{c.provider ?? "fallback"}{c.model ? ` · ${c.model}` : ""}</td>
                            <td className="py-3 px-2 text-xs font-mono">{c.latency_ms != null ? `${c.latency_ms} ms` : "—"}</td>
                            <td className="py-3 px-2 text-xs font-mono">{c.total_tokens ?? "—"}</td>
                            <td className="py-3 px-2">
                              <div className="flex flex-wrap gap-1">
                                {c.degraded && <Badge variant="warning">degraded</Badge>}
                                {c.guardrail_triggered && <Badge variant="warning">guardrail</Badge>}
                                {c.citations_dropped && <Badge variant="error">citations dropped</Badge>}
                                {!c.degraded && !c.guardrail_triggered && !c.citations_dropped && (
                                  <span className="text-xs text-[var(--muted-foreground)]">—</span>
                                )}
                              </div>
                            </td>
                            <td className="py-3 px-2 text-xs font-mono">
                              {c.cost_estimate != null ? `$${c.cost_estimate.toFixed(6)}` : "—"}
                            </td>
                            <td className="py-3 px-2 text-xs text-[var(--muted-foreground)]">
                              {new Date(c.created_at).toLocaleString()}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </CardContent>
            </Card>
          </>
        )}
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Uploads last 7 days */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-base flex items-center gap-2">
                <Activity className="h-5 w-5 text-blue-500" />
                Document Ingestion — Last 7 Days
              </h2>
              <Badge variant="info">Real</Badge>
            </div>
          </CardHeader>
          <CardContent>
            <div className="flex h-40 items-end justify-between gap-2">
              {overview.uploads_last_7_days.map((d) => (
                <div key={d.date} className="flex flex-1 flex-col items-center gap-1">
                  <span className="text-xs font-semibold text-[var(--muted-foreground)]">{d.count}</span>
                  <div
                    className="w-full max-w-10 rounded-t-md bg-gradient-to-t from-blue-600 to-indigo-400 transition-all"
                    style={{ height: `${Math.max(6, (d.count / maxDay) * 100)}px` }}
                  />
                  <span className="text-[10px] text-[var(--muted-foreground)]">
                    {new Date(d.date).toLocaleDateString(undefined, { weekday: "short" })}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Document status breakdown */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-base flex items-center gap-2">
                <FileText className="h-5 w-5 text-emerald-500" />
                Document Processing Pipeline
              </h2>
              <Badge variant="info">{totalDocs} total</Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {["INDEXED", "PROCESSING", "PENDING", "FAILED"].map((status) => {
              const count = byStatus[status] || 0;
              const pct = totalDocs ? Math.round((count / totalDocs) * 100) : 0;
              return (
                <div key={status} className="space-y-1">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-medium">{status}</span>
                    <span className="text-[var(--muted-foreground)]">
                      {count} ({pct}%)
                    </span>
                  </div>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-[var(--muted)]">
                    <div className={`h-full ${barColor(status)} transition-all duration-500`} style={{ width: `${pct}%` }} />
                  </div>
                </div>
              );
            })}
            {totalDocs === 0 && (
              <p className="pt-2 text-center text-sm text-[var(--muted-foreground)]">
                No documents processed yet.
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Workspace footprint */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-base flex items-center gap-2">
                <FolderKanban className="h-5 w-5 text-purple-500" />
                Workspace Footprint
              </h2>
            </div>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-3 gap-4 text-center">
              <div>
                <Building2 className="mx-auto mb-1 h-6 w-6 text-indigo-500" />
                <p className="text-xl font-bold">{overview.organizations}</p>
                <p className="text-xs text-[var(--muted-foreground)]">Organizations</p>
              </div>
              <div>
                <FolderKanban className="mx-auto mb-1 h-6 w-6 text-purple-500" />
                <p className="text-xl font-bold">{overview.workspaces}</p>
                <p className="text-xs text-[var(--muted-foreground)]">Workspaces</p>
              </div>
              <div>
                <Cpu className="mx-auto mb-1 h-6 w-6 text-blue-500" />
                <p className="text-xl font-bold">{overview.chunks.toLocaleString()}</p>
                <p className="text-xs text-[var(--muted-foreground)]">Chunks</p>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Recent workflow runs */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-base flex items-center gap-2">
                <GitBranch className="h-5 w-5 text-amber-500" />
                Recent Workflow Runs
              </h2>
              <Badge variant="info">
                {Object.entries(runByStatus)
                  .map(([k, v]) => `${k}: ${v}`)
                  .join(" · ") || "none"}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            {overview.recent_runs.length === 0 ? (
              <p className="py-4 text-center text-sm text-[var(--muted-foreground)]">
                No workflow runs yet. Create one in the Workflows page.
              </p>
            ) : (
              overview.recent_runs.map((r, i) => (
                <div
                  key={i}
                  className="flex items-center justify-between rounded-lg border border-[var(--border)] px-3 py-2"
                >
                  <span className="text-xs font-mono truncate">{r.workflow_id.slice(0, 8)}</span>
                  <Badge
                    variant={
                      r.status === "COMPLETED"
                        ? "success"
                        : r.status === "FAILED"
                        ? "error"
                        : "warning"
                    }
                  >
                    {r.status}
                  </Badge>
                  <span className="text-[11px] text-[var(--muted-foreground)]">
                    {r.completed_at || r.started_at
                      ? new Date(r.completed_at || r.started_at || "").toLocaleTimeString()
                      : "—"}
                  </span>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>

      {/* Recent activity */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-base flex items-center gap-2">
              <Activity className="h-5 w-5 text-emerald-500" />
              Recent Activity (Audit Log)
            </h2>
          </div>
        </CardHeader>
        <CardContent>
          {overview.recent_activity.length === 0 ? (
            <p className="py-4 text-center text-sm text-[var(--muted-foreground)]">
              No activity recorded yet.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-[var(--border)] text-xs text-[var(--muted-foreground)] uppercase">
                  <tr>
                    <th className="py-3 px-2">Action</th>
                    <th className="py-3 px-2">Details</th>
                    <th className="py-3 px-2">Time</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border)]">
                  {overview.recent_activity.map((a, i) => (
                    <tr key={i} className="hover:bg-[var(--muted)]/50 transition">
                      <td className="py-3 px-2 font-medium">{actionLabel(a.action)}</td>
                      <td className="py-3 px-2 text-xs text-[var(--muted-foreground)] max-w-md truncate">
                        {a.details ? JSON.stringify(a.details) : "—"}
                      </td>
                      <td className="py-3 px-2 text-xs text-[var(--muted-foreground)]">
                        {new Date(a.created_at).toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Document table */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-base">Documents Processed</h2>
            <Badge variant="info">{docTotal} documents</Badge>
          </div>
        </CardHeader>
        <CardContent>
          {docRows.length === 0 ? (
            <p className="py-4 text-center text-sm text-[var(--muted-foreground)]">
              No documents found in your workspaces.
            </p>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="border-b border-[var(--border)] text-xs text-[var(--muted-foreground)] uppercase">
                    <tr>
                      <th className="py-3 px-2">Title</th>
                      <th className="py-3 px-2">Workspace</th>
                      <th className="py-3 px-2">Chunks</th>
                      <th className="py-3 px-2">Status</th>
                      <th className="py-3 px-2">Uploaded</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border)]">
                    {docRows.map((d) => (
                    <tr key={d.id} className="hover:bg-[var(--muted)]/50 transition">
                      <td className="py-3 px-2 font-medium max-w-xs truncate">{d.title}</td>
                      <td className="py-3 px-2 text-xs text-[var(--muted-foreground)]">{d.workspace}</td>
                      <td className="py-3 px-2 text-xs font-mono">{d.chunk_count}</td>
                      <td className="py-3 px-2">
                        <Badge
                          variant={
                            d.status === "INDEXED"
                              ? "success"
                              : d.status === "FAILED"
                              ? "error"
                              : "warning"
                          }
                        >
                          {d.status}
                        </Badge>
                      </td>
                      <td className="py-3 px-2 text-xs text-[var(--muted-foreground)]">
                        {new Date(d.created_at).toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
              {docRows.length < docTotal && (
                <div className="flex justify-center pt-3">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => docsQuery.fetchNextPage()}
                    disabled={docsQuery.isFetchingNextPage || !docsQuery.hasNextPage}
                  >
                    {docsQuery.isFetchingNextPage ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Activity className="h-4 w-4" />
                    )}
                    Load More ({docRows.length} of {docTotal})
                  </Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
