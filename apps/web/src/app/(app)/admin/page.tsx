"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Building2, FileText, Plug, GitBranch, Users, ShieldAlert } from "lucide-react";
import { orgApi, type Organization } from "@/lib/api";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";

/**
 * Single-org assumption, matching the rest of the settings area
 * (settings/team/page.tsx's useCurrentOrg): admin overview is for the first
 * organization the user belongs to.
 */
function useCurrentOrg() {
  return useQuery({
    queryKey: ["orgs", "current"],
    queryFn: async (): Promise<Organization | null> => {
      const orgs = await orgApi.list();
      return orgs.items[0] ?? null;
    },
  });
}

export default function AdminConsolePage() {
  const orgQuery = useCurrentOrg();
  const org = orgQuery.data;

  const overviewQuery = useQuery({
    queryKey: ["admin-overview", org?.id],
    queryFn: () => orgApi.adminWorkspaces(org!.id),
    enabled: !!org,
    retry: false,
  });

  const forbidden =
    overviewQuery.isError &&
    overviewQuery.error instanceof Error &&
    overviewQuery.error.message.toLowerCase().includes("permission");

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div>
        <Link
          href="/settings"
          className="mb-2 inline-flex items-center gap-1 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Settings
        </Link>
        <h1 className="text-2xl font-bold">Admin Console</h1>
        <p className="text-sm text-[var(--muted-foreground)]">
          Cross-workspace overview for {org?.name ?? "your organization"}
        </p>
      </div>

      {overviewQuery.isLoading && (
        <Card>
          <CardContent className="py-8 text-center text-sm text-[var(--muted-foreground)]">
            Loading...
          </CardContent>
        </Card>
      )}

      {overviewQuery.isError && (
        <Card>
          <CardContent className="flex flex-col items-center gap-2 py-8 text-center">
            <ShieldAlert className="h-8 w-8 text-[var(--muted-foreground)]" />
            <p className="text-sm font-medium">
              {forbidden
                ? "You need an admin or owner role to view the admin console."
                : "Failed to load the admin overview."}
            </p>
          </CardContent>
        </Card>
      )}

      {overviewQuery.data && (
        <>
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <Building2 className="h-5 w-5" />
                <h2 className="font-semibold">{overviewQuery.data.organization_name}</h2>
              </div>
            </CardHeader>
            <CardContent className="flex items-center gap-6 text-sm">
              <div className="flex items-center gap-1.5">
                <Users className="h-4 w-4 text-[var(--muted-foreground)]" />
                <span>{overviewQuery.data.member_count} member(s)</span>
              </div>
              <div className="flex items-center gap-1.5">
                <Building2 className="h-4 w-4 text-[var(--muted-foreground)]" />
                <span>{overviewQuery.data.workspaces.length} workspace(s)</span>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <h2 className="font-semibold">Workspaces</h2>
            </CardHeader>
            <CardContent className="divide-y divide-[var(--border)] p-0">
              {overviewQuery.data.workspaces.length === 0 ? (
                <p className="p-4 text-sm text-[var(--muted-foreground)]">
                  No workspaces in this organization yet.
                </p>
              ) : (
                overviewQuery.data.workspaces.map((ws) => (
                  <Link
                    key={ws.id}
                    href={`/documents?workspace_id=${ws.id}`}
                    className="block p-4 hover:bg-[var(--muted)]"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium">{ws.name}</p>
                        {ws.description && (
                          <p className="truncate text-xs text-[var(--muted-foreground)]">
                            {ws.description}
                          </p>
                        )}
                        {ws.creator_name && (
                          <p className="text-xs text-[var(--muted-foreground)]">
                            Created by {ws.creator_name} ·{" "}
                            {new Date(ws.created_at).toLocaleDateString()}
                          </p>
                        )}
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <Badge variant="default">
                          <FileText className="mr-1 h-3 w-3" />
                          {ws.document_count}
                        </Badge>
                        <Badge variant="default">
                          <Plug className="mr-1 h-3 w-3" />
                          {ws.connector_count}
                        </Badge>
                        <Badge variant="default">
                          <GitBranch className="mr-1 h-3 w-3" />
                          {ws.workflow_count}
                        </Badge>
                      </div>
                    </div>
                  </Link>
                ))
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
