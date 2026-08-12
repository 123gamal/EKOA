"use client";

import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Github,
  Loader2,
  RefreshCw,
  Unplug,
  CheckCircle2,
  AlertTriangle,
  Database,
  Clock,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Badge } from "@/components/ui/Badge";
import { connectorApi, type Connector } from "@/lib/api";
import { queryKeys, useConnectors } from "@/lib/queries";
import {
  connectConnectorSchema,
  type ConnectConnectorValues,
} from "@/lib/validation";

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

function connectorRepoName(connector: Connector): string {
  const c = connector.config;
  if (c?.owner && c?.repo) return `${c.owner}/${c.repo}`;
  return connector.name;
}

export function GitHubConnectorPanel({ workspaces }: { workspaces: { id: string; name: string }[] }) {
  const queryClient = useQueryClient();
  const [selectedWs, setSelectedWs] = useState(workspaces[0]?.id ?? "");
  const [formError, setFormError] = useState("");
  const [formSuccess, setFormSuccess] = useState("");

  const connectorsQuery = useConnectors(selectedWs || undefined);
  const connectors = connectorsQuery.data?.items ?? [];

  const {
    register,
    handleSubmit,
    reset,
    setValue,
    formState: { errors },
  } = useForm<ConnectConnectorValues>({
    resolver: zodResolver(connectConnectorSchema),
    defaultValues: { workspaceId: selectedWs, name: "", owner: "", repo: "", accessToken: "" },
  });

  // `workspaces` arrives asynchronously (useAllWorkspaces is a react-query
  // hook), so it's always [] on first render — the useState initializer
  // above only runs once and never re-evaluates once workspaces populates.
  // Without this, selectedWs (and the form's workspaceId) stay "" forever,
  // permanently disabling "Connect Repository" until the user manually
  // touches the dropdown.
  useEffect(() => {
    if (!selectedWs && workspaces.length > 0) {
      setSelectedWs(workspaces[0].id);
      setValue("workspaceId", workspaces[0].id);
    }
  }, [workspaces, selectedWs, setValue]);

  const connectMutation = useMutation({
    mutationFn: (values: ConnectConnectorValues) =>
      connectorApi.connect({
        provider: "github",
        workspace_id: values.workspaceId,
        name: values.name,
        access_token: values.accessToken,
        config: { owner: values.owner, repo: values.repo },
      }),
    onSuccess: () => {
      setFormError("");
      setFormSuccess("GitHub repository connected. Run a sync to index its documentation.");
      reset({ workspaceId: selectedWs, name: "", owner: "", repo: "", accessToken: "" });
      queryClient.invalidateQueries({ queryKey: queryKeys.connectors(selectedWs) });
    },
    onError: (err: Error) => {
      setFormSuccess("");
      setFormError(err.message);
    },
  });

  const syncMutation = useMutation({
    mutationFn: (id: string) => connectorApi.sync(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.connectors(selectedWs) });
    },
    onError: (err: Error) => setFormError(err.message),
  });

  const disconnectMutation = useMutation({
    mutationFn: (id: string) => connectorApi.disconnect(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.connectors(selectedWs) });
    },
    onError: (err: Error) => setFormError(err.message),
  });

  const onSubmit = (values: ConnectConnectorValues) => {
    setFormError("");
    setFormSuccess("");
    connectMutation.mutate(values);
  };

  return (
    <div className="space-y-6">
      {/* Connect form */}
      <div>
        <div className="mb-4 flex items-center gap-2">
          <Github className="h-5 w-5" />
          <h2 className="font-semibold">GitHub Integration</h2>
        </div>

        <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
          <div>
            <label htmlFor="connector-ws" className="block text-sm font-medium">
              Workspace
            </label>
            <select
              id="connector-ws"
              className="mt-1 w-full rounded-lg border border-[var(--border)] bg-transparent px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
              value={selectedWs}
              onChange={(e) => {
                const next = e.target.value;
                setSelectedWs(next);
                reset((prev) => ({ ...prev, workspaceId: next }));
              }}
            >
              {workspaces.map((ws) => (
                <option key={ws.id} value={ws.id}>
                  {ws.name}
                </option>
              ))}
            </select>
            {errors.workspaceId && (
              <p className="text-xs text-red-500">{errors.workspaceId.message}</p>
            )}
          </div>

          <Input
            label="Integration Name"
            id="connector-name"
            placeholder="e.g. Internal Platform Docs"
            error={errors.name?.message}
            {...register("name")}
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <Input
              label="Repository Owner"
              id="connector-owner"
              placeholder="e.g. acme-corp"
              error={errors.owner?.message}
              {...register("owner")}
            />
            <Input
              label="Repository"
              id="connector-repo"
              placeholder="e.g. platform-docs"
              error={errors.repo?.message}
              {...register("repo")}
            />
          </div>
          <Input
            label="Personal Access Token"
            id="connector-pat"
            type="password"
            placeholder="github_pat_..."
            error={errors.accessToken?.message}
            {...register("accessToken")}
          />

          {formError && (
            <p role="alert" className="text-sm text-red-500">
              {formError}
            </p>
          )}
          {formSuccess && (
            <p role="status" className="text-sm text-green-600">
              {formSuccess}
            </p>
          )}

          <Button type="submit" disabled={connectMutation.isPending || !selectedWs}>
            {connectMutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Validating...
              </>
            ) : (
              "Connect Repository"
            )}
          </Button>
        </form>
      </div>

      {/* Connected integrations */}
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
            {connectors.map((connector) => (
              <li
                key={connector.id}
                className="rounded-lg border border-[var(--border)] p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <Github className="h-4 w-4 shrink-0" />
                      <span className="truncate font-medium">{connector.name}</span>
                      <Badge variant={STATUS_VARIANT[connector.status] ?? "default"}>
                        {connector.status}
                      </Badge>
                    </div>
                    <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                      {connectorRepoName(connector)} ·{" "}
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
                    Documentation indexed and searchable via chat/RAG.
                  </p>
                )}
                {connector.last_sync_status === "running" && (
                  <p className="mt-2 flex items-center gap-1 text-xs text-[var(--muted-foreground)]">
                    <Database className="h-3 w-3 animate-pulse" />
                    Syncing repository content...
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
