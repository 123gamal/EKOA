"use client";

import { useQuery } from "@tanstack/react-query";
import { connectorApi, orgApi, workspaceApi, type Workspace } from "@/lib/api";

export const queryKeys = {
  orgs: ["orgs"] as const,
  workspaces: ["workspaces"] as const,
  templates: ["workflow-templates"] as const,
  connectors: (workspaceId: string) => ["connectors", workspaceId] as const,
  connectorHealth: (id: string) => ["connector-health", id] as const,
};

/**
 * Load every workspace the current user can see, across all of their
 * organizations. Cached under one key so Documents / Chat / Workflows no
 * longer each run their own duplicated fetch loop.
 */
export function useAllWorkspaces() {
  return useQuery({
    queryKey: [...queryKeys.workspaces],
    queryFn: async (): Promise<Workspace[]> => {
      const orgs = await orgApi.list();
      const all: Workspace[] = [];
      for (const org of orgs.items) {
        const ws = await workspaceApi.list(org.id);
        all.push(...ws.items);
      }
      return all;
    },
  });
}

/**
 * Connectors in a workspace. Polled while any connector's last sync is still
 * running so the UI reflects task completion without manual polling.
 */
export function useConnectors(workspaceId: string | undefined) {
  return useQuery({
    queryKey: [...queryKeys.connectors(workspaceId ?? "none")],
    queryFn: () => connectorApi.list(workspaceId!),
    enabled: !!workspaceId,
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      const running = items.some((c) => c.last_sync_status === "running");
      return running ? 2000 : false;
    },
  });
}

/** Real connector health: token validity + last sync state. */
export function useConnectorHealth(id: string | undefined) {
  return useQuery({
    queryKey: [...queryKeys.connectorHealth(id ?? "none")],
    queryFn: () => connectorApi.health(id!),
    enabled: !!id,
    refetchInterval: (query) =>
      query.state.data?.last_sync_status === "running" ? 2000 : false,
  });
}
