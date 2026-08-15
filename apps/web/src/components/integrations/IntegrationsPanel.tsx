"use client";

import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Github,
  Kanban,
  FileText,
  MessageSquare,
  HardDrive,
  Loader2,
  RefreshCw,
  Unplug,
  CheckCircle2,
  AlertTriangle,
  Database,
  Clock,
  ExternalLink,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Badge } from "@/components/ui/Badge";
import { connectorApi, type Connector } from "@/lib/api";
import { queryKeys, useConnectors } from "@/lib/queries";
import {
  connectConnectorSchema,
  connectJiraSchema,
  connectNotionSchema,
  type ConnectConnectorValues,
  type ConnectJiraValues,
  type ConnectNotionValues,
} from "@/lib/validation";

type Provider = "github" | "jira" | "notion" | "slack" | "google_drive";

const PROVIDER_META: Record<Provider, { label: string; icon: typeof Github; authType: "pat" | "oauth2" }> = {
  github: { label: "GitHub", icon: Github, authType: "pat" },
  jira: { label: "Jira", icon: Kanban, authType: "pat" },
  notion: { label: "Notion", icon: FileText, authType: "pat" },
  slack: { label: "Slack", icon: MessageSquare, authType: "oauth2" },
  google_drive: { label: "Google Drive", icon: HardDrive, authType: "oauth2" },
};

const STATUS_VARIANT: Record<string, "success" | "error" | "warning" | "info" | "default"> = {
  connected: "success",
  error: "error",
  disconnected: "default",
};

const SYNC_VARIANT: Record<string, "success" | "error" | "warning" | "default"> = {
  success: "success",
  failed: "error",
  running: "warning",
};

function connectorSubtitle(connector: Connector): string {
  const c = connector.config as Record<string, unknown> | null;
  if (c?.owner && c?.repo) return `${c.owner}/${c.repo}`;
  if (c?.project_key) return `Project ${c.project_key}`;
  if (c?.title) return String(c.title);
  if (c?.team_name) return `Slack workspace: ${c.team_name}`;
  if (c?.account) return String(c.account);
  return connector.name;
}

function providerIcon(provider: string) {
  const meta = PROVIDER_META[provider as Provider];
  return meta ? meta.icon : Github;
}

export function IntegrationsPanel({ workspaces }: { workspaces: { id: string; name: string }[] }) {
  const queryClient = useQueryClient();
  const [selectedWs, setSelectedWs] = useState(workspaces[0]?.id ?? "");
  const [activeProvider, setActiveProvider] = useState<Provider>("github");
  const [formError, setFormError] = useState("");
  const [formSuccess, setFormSuccess] = useState("");

  const connectorsQuery = useConnectors(selectedWs || undefined);
  const connectors = connectorsQuery.data?.items ?? [];

  useEffect(() => {
    if (!selectedWs && workspaces.length > 0) {
      setSelectedWs(workspaces[0].id);
    }
  }, [workspaces, selectedWs]);

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.connectors(selectedWs) });

  const connectMutation = useMutation({
    mutationFn: (data: { provider: string; name: string; accessToken: string; config: Record<string, string> }) =>
      connectorApi.connect({
        provider: data.provider,
        workspace_id: selectedWs,
        name: data.name,
        access_token: data.accessToken,
        config: data.config,
      }),
    onSuccess: () => {
      setFormError("");
      setFormSuccess("Connected. Run a sync to index its content.");
      invalidate();
    },
    onError: (err: Error) => {
      setFormSuccess("");
      setFormError(err.message);
    },
  });

  const oauthMutation = useMutation({
    mutationFn: (provider: string) => connectorApi.connectOAuth(provider, selectedWs),
    onError: (err: Error) => setFormError(err.message),
  });

  const syncMutation = useMutation({
    mutationFn: (id: string) => connectorApi.sync(id),
    onSuccess: invalidate,
    onError: (err: Error) => setFormError(err.message),
  });

  const disconnectMutation = useMutation({
    mutationFn: (id: string) => connectorApi.disconnect(id),
    onSuccess: invalidate,
    onError: (err: Error) => setFormError(err.message),
  });

  return (
    <div className="space-y-6">
      <div>
        <div className="mb-4 flex flex-wrap gap-2">
          {(Object.keys(PROVIDER_META) as Provider[]).map((p) => {
            const meta = PROVIDER_META[p];
            const Icon = meta.icon;
            return (
              <button
                key={p}
                type="button"
                onClick={() => {
                  setActiveProvider(p);
                  setFormError("");
                  setFormSuccess("");
                }}
                className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm transition-colors ${
                  activeProvider === p
                    ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--primary)]"
                    : "border-[var(--border)] hover:bg-[var(--muted)]"
                }`}
              >
                <Icon className="h-4 w-4" />
                {meta.label}
              </button>
            );
          })}
        </div>

        <div className="mb-4">
          <label htmlFor="connector-ws" className="block text-sm font-medium">
            Workspace
          </label>
          <select
            id="connector-ws"
            className="mt-1 w-full rounded-lg border border-[var(--border)] bg-transparent px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
            value={selectedWs}
            onChange={(e) => setSelectedWs(e.target.value)}
          >
            {workspaces.map((ws) => (
              <option key={ws.id} value={ws.id}>
                {ws.name}
              </option>
            ))}
          </select>
        </div>

        {activeProvider === "github" && (
          <GitHubForm
            workspaceId={selectedWs}
            isPending={connectMutation.isPending}
            onSubmit={(v) =>
              connectMutation.mutate({
                provider: "github",
                name: v.name,
                accessToken: v.accessToken,
                config: { owner: v.owner, repo: v.repo },
              })
            }
          />
        )}
        {activeProvider === "jira" && (
          <JiraForm
            workspaceId={selectedWs}
            isPending={connectMutation.isPending}
            onSubmit={(v) =>
              connectMutation.mutate({
                provider: "jira",
                name: v.name,
                accessToken: `${v.email}:${v.apiToken}`,
                config: { base_url: v.baseUrl, project_key: v.projectKey },
              })
            }
          />
        )}
        {activeProvider === "notion" && (
          <NotionForm
            workspaceId={selectedWs}
            isPending={connectMutation.isPending}
            onSubmit={(v) =>
              connectMutation.mutate({
                provider: "notion",
                name: v.name,
                accessToken: v.accessToken,
                config: { [v.resourceType]: v.resourceId },
              })
            }
          />
        )}
        {(activeProvider === "slack" || activeProvider === "google_drive") && (
          <div className="space-y-3 rounded-lg border border-[var(--border)] p-4">
            <p className="text-sm text-[var(--muted-foreground)]">
              {PROVIDER_META[activeProvider].label} uses OAuth — you&apos;ll be redirected to sign
              in and approve access, then brought back here.
            </p>
            <Button
              disabled={!selectedWs || oauthMutation.isPending}
              onClick={() => oauthMutation.mutate(activeProvider)}
            >
              {oauthMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <ExternalLink className="h-4 w-4" />
              )}
              Connect {PROVIDER_META[activeProvider].label}
            </Button>
          </div>
        )}

        {formError && (
          <p role="alert" className="mt-3 text-sm text-red-500">
            {formError}
          </p>
        )}
        {formSuccess && (
          <p role="status" className="mt-3 text-sm text-green-600">
            {formSuccess}
          </p>
        )}
      </div>

      {/* Connected integrations, across every provider */}
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[var(--muted-foreground)]">
            Connected Integrations
          </h3>
          {connectorsQuery.isFetching && (
            <Loader2 className="h-4 w-4 animate-spin text-[var(--muted-foreground)]" />
          )}
        </div>

        {connectors.length === 0 ? (
          <p className="text-sm text-[var(--muted-foreground)]">
            {selectedWs ? "No integrations connected in this workspace yet." : "Select a workspace to see integrations."}
          </p>
        ) : (
          <ul className="space-y-3">
            {connectors.map((connector) => {
              const Icon = providerIcon(connector.provider);
              return (
                <li key={connector.id} className="rounded-lg border border-[var(--border)] p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <Icon className="h-4 w-4 shrink-0" />
                        <span className="truncate font-medium">{connector.name}</span>
                        <Badge variant={STATUS_VARIANT[connector.status] ?? "default"}>
                          {connector.status}
                        </Badge>
                      </div>
                      <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                        {connectorSubtitle(connector)} ·{" "}
                        {connector.last_sync_status ? (
                          <span className="inline-flex items-center gap-1">
                            <Clock className="h-3 w-3" />
                            Last sync:{" "}
                            <Badge
                              variant={SYNC_VARIANT[connector.last_sync_status] ?? "default"}
                              animated={connector.last_sync_status === "running"}
                            >
                              {connector.last_sync_status}
                            </Badge>
                          </span>
                        ) : (
                          "Never synced"
                        )}
                      </p>
                      {connector.last_sync_at && (
                        <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                          {new Date(connector.last_sync_at).toLocaleString()}
                          {connector.last_sync_document_count != null
                            ? ` · ${connector.last_sync_document_count} files`
                            : ""}
                        </p>
                      )}
                      {connector.status_reason && (
                        <p className="mt-1 flex items-center gap-1 text-xs text-red-500">
                          <AlertTriangle className="h-3 w-3" />
                          {connector.status_reason}
                        </p>
                      )}
                      {connector.last_sync_error && (
                        <p className="mt-1 flex items-center gap-1 text-xs text-red-500">
                          <AlertTriangle className="h-3 w-3" />
                          {connector.last_sync_error}
                        </p>
                      )}
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      {connector.status === "connected" && (
                        <Button
                          variant="secondary"
                          size="sm"
                          disabled={syncMutation.isPending || connector.last_sync_status === "running"}
                          onClick={() => syncMutation.mutate(connector.id)}
                        >
                          {syncMutation.isPending && syncMutation.variables === connector.id ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <RefreshCw className="h-3 w-3" />
                          )}
                          Sync Now
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={disconnectMutation.isPending}
                        onClick={() => disconnectMutation.mutate(connector.id)}
                      >
                        <Unplug className="h-3 w-3" />
                        Disconnect
                      </Button>
                    </div>
                  </div>
                  {connector.last_sync_status === "success" && (
                    <p className="mt-2 flex items-center gap-1 text-xs text-green-600">
                      <CheckCircle2 className="h-3 w-3" />
                      Content indexed and searchable via chat/RAG.
                    </p>
                  )}
                  {connector.last_sync_status === "running" && (
                    <p className="mt-2 flex items-center gap-1 text-xs text-[var(--muted-foreground)]">
                      <Database className="h-3 w-3 animate-pulse" />
                      Syncing content...
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}

function GitHubForm({
  workspaceId,
  isPending,
  onSubmit,
}: {
  workspaceId: string;
  isPending: boolean;
  onSubmit: (v: ConnectConnectorValues) => void;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ConnectConnectorValues>({
    resolver: zodResolver(connectConnectorSchema),
    defaultValues: { workspaceId, name: "", owner: "", repo: "", accessToken: "" },
  });
  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
      <Input label="Integration Name" placeholder="e.g. Internal Platform Docs" error={errors.name?.message} {...register("name")} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Input label="Repository Owner" placeholder="e.g. acme-corp" error={errors.owner?.message} {...register("owner")} />
        <Input label="Repository" placeholder="e.g. platform-docs" error={errors.repo?.message} {...register("repo")} />
      </div>
      <Input label="Personal Access Token" type="password" placeholder="github_pat_..." error={errors.accessToken?.message} {...register("accessToken")} />
      <Button type="submit" disabled={isPending || !workspaceId}>
        {isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
        Connect Repository
      </Button>
    </form>
  );
}

function JiraForm({
  workspaceId,
  isPending,
  onSubmit,
}: {
  workspaceId: string;
  isPending: boolean;
  onSubmit: (v: ConnectJiraValues) => void;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ConnectJiraValues>({
    resolver: zodResolver(connectJiraSchema),
    defaultValues: { workspaceId, name: "", baseUrl: "", projectKey: "", email: "", apiToken: "" },
  });
  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
      <Input label="Integration Name" placeholder="e.g. Engineering Board" error={errors.name?.message} {...register("name")} />
      <Input label="Base URL" placeholder="https://yourcompany.atlassian.net" error={errors.baseUrl?.message} {...register("baseUrl")} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Input label="Project Key" placeholder="e.g. ENG" error={errors.projectKey?.message} {...register("projectKey")} />
        <Input label="Email" type="email" placeholder="you@company.com" error={errors.email?.message} {...register("email")} />
      </div>
      <Input label="API Token" type="password" error={errors.apiToken?.message} {...register("apiToken")} />
      <Button type="submit" disabled={isPending || !workspaceId}>
        {isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
        Connect Jira Project
      </Button>
    </form>
  );
}

function NotionForm({
  workspaceId,
  isPending,
  onSubmit,
}: {
  workspaceId: string;
  isPending: boolean;
  onSubmit: (v: ConnectNotionValues) => void;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ConnectNotionValues>({
    resolver: zodResolver(connectNotionSchema),
    defaultValues: { workspaceId, name: "", resourceId: "", resourceType: "page_id", accessToken: "" },
  });
  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
      <Input label="Integration Name" placeholder="e.g. Team Wiki" error={errors.name?.message} {...register("name")} />
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1">
          <label className="block text-sm font-medium">Resource Type</label>
          <select
            className="w-full rounded-lg border border-[var(--border)] bg-transparent px-4 py-2 text-sm"
            {...register("resourceType")}
          >
            <option value="page_id">Page</option>
            <option value="database_id">Database</option>
          </select>
        </div>
        <Input label="Page or Database ID" error={errors.resourceId?.message} {...register("resourceId")} />
      </div>
      <Input label="Internal Integration Secret" type="password" placeholder="secret_... or ntn_..." error={errors.accessToken?.message} {...register("accessToken")} />
      <Button type="submit" disabled={isPending || !workspaceId}>
        {isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
        Connect Notion
      </Button>
    </form>
  );
}
