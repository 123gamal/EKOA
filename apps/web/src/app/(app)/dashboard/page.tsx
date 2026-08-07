"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { Plus, FolderOpen, MessageSquare, FileText } from "lucide-react";
import { orgApi, workspaceApi, type Organization, type Workspace } from "@/lib/api";
import { slugify } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";

export default function DashboardPage() {
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedOrg, setSelectedOrg] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [showOrgForm, setShowOrgForm] = useState(false);
  const [orgName, setOrgName] = useState("");
  const [orgSlug, setOrgSlug] = useState("");
  const [orgDesc, setOrgDesc] = useState("");
  const [creatingOrg, setCreatingOrg] = useState(false);

  const [showWsForm, setShowWsForm] = useState(false);
  const [wsName, setWsName] = useState("");
  const [wsDesc, setWsDesc] = useState("");
  const [creatingWs, setCreatingWs] = useState(false);

  useEffect(() => {
    orgApi
      .list()
      .then((data) => {
        setOrgs(data.items);
        if (data.items.length > 0) setSelectedOrg(data.items[0].id);
        if (data.items.length === 0) setShowOrgForm(true);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedOrg) {
      setWorkspaces([]);
      return;
    }
    workspaceApi
      .list(selectedOrg)
      .then((data) => setWorkspaces(data.items))
      .catch((e) => setError(e.message));
  }, [selectedOrg]);

  async function handleCreateOrg(e: FormEvent) {
    e.preventDefault();
    setCreatingOrg(true);
    setError("");
    try {
      const org = await orgApi.create({
        name: orgName,
        slug: orgSlug || slugify(orgName),
        description: orgDesc || undefined,
      });
      setOrgs((prev) => [...prev, org]);
      setSelectedOrg(org.id);
      setShowOrgForm(false);
      setShowWsForm(true);
      setOrgName("");
      setOrgSlug("");
      setOrgDesc("");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to create organization");
    } finally {
      setCreatingOrg(false);
    }
  }

  async function handleCreateWorkspace(e: FormEvent) {
    e.preventDefault();
    if (!selectedOrg) return;
    setCreatingWs(true);
    setError("");
    try {
      const ws = await workspaceApi.create({
        name: wsName,
        description: wsDesc || undefined,
        organization_id: selectedOrg,
      });
      setWorkspaces((prev) => [...prev, ws]);
      setShowWsForm(false);
      setWsName("");
      setWsDesc("");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to create workspace");
    } finally {
      setCreatingWs(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <p className="text-[var(--muted-foreground)]">Loading dashboard...</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold">Dashboard</h1>
          <p className="text-sm text-[var(--muted-foreground)]">
            Manage organizations, workspaces, and quick actions
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => setShowOrgForm((v) => !v)}>
          <Plus className="h-4 w-4" />
          New Organization
        </Button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-400">
          {error}
        </div>
      )}

      {showOrgForm && (
        <Card>
          <CardHeader>
            <h2 className="font-semibold">Create Organization</h2>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleCreateOrg} className="grid gap-4 sm:grid-cols-2">
              <Input
                label="Organization Name"
                id="org-name"
                value={orgName}
                onChange={(e) => {
                  setOrgName(e.target.value);
                  if (!orgSlug) setOrgSlug(slugify(e.target.value));
                }}
                required
              />
              <Input
                label="Slug"
                id="org-slug"
                value={orgSlug}
                onChange={(e) => setOrgSlug(e.target.value)}
                pattern="^[a-z0-9-]+$"
                required
              />
              <div className="sm:col-span-2">
                <Input
                  label="Description (optional)"
                  id="org-desc"
                  value={orgDesc}
                  onChange={(e) => setOrgDesc(e.target.value)}
                />
              </div>
              <div className="sm:col-span-2 flex gap-2">
                <Button type="submit" disabled={creatingOrg}>
                  {creatingOrg ? "Creating..." : "Create Organization"}
                </Button>
                {orgs.length > 0 && (
                  <Button type="button" variant="secondary" onClick={() => setShowOrgForm(false)}>
                    Cancel
                  </Button>
                )}
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {orgs.length > 0 && (
        <section>
          <h2 className="mb-4 text-lg font-semibold">Organizations</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {orgs.map((org) => (
              <button
                key={org.id}
                onClick={() => setSelectedOrg(org.id)}
                className={`rounded-xl border p-4 text-left transition ${
                  selectedOrg === org.id
                    ? "border-[var(--primary)] bg-[var(--primary)]/5"
                    : "border-[var(--border)] hover:bg-[var(--muted)]"
                }`}
              >
                <h3 className="font-medium">{org.name}</h3>
                <p className="text-sm text-[var(--muted-foreground)]">{org.slug}</p>
              </button>
            ))}
          </div>
        </section>
      )}

      {selectedOrg && (
        <section>
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-semibold">Workspaces</h2>
            <Button variant="secondary" size="sm" onClick={() => setShowWsForm((v) => !v)}>
              <Plus className="h-4 w-4" />
              New Workspace
            </Button>
          </div>

          {showWsForm && (
            <Card className="mb-4">
              <CardContent className="pt-4">
                <form onSubmit={handleCreateWorkspace} className="grid gap-4 sm:grid-cols-2">
                  <Input
                    label="Workspace Name"
                    id="ws-name"
                    value={wsName}
                    onChange={(e) => setWsName(e.target.value)}
                    required
                  />
                  <Input
                    label="Description (optional)"
                    id="ws-desc"
                    value={wsDesc}
                    onChange={(e) => setWsDesc(e.target.value)}
                  />
                  <div className="sm:col-span-2 flex gap-2">
                    <Button type="submit" disabled={creatingWs}>
                      {creatingWs ? "Creating..." : "Create Workspace"}
                    </Button>
                    <Button type="button" variant="secondary" onClick={() => setShowWsForm(false)}>
                      Cancel
                    </Button>
                  </div>
                </form>
              </CardContent>
            </Card>
          )}

          {workspaces.length === 0 ? (
            <Card>
              <CardContent className="py-8 text-center">
                <FolderOpen className="mx-auto mb-3 h-10 w-10 text-[var(--muted-foreground)]" />
                <p className="text-[var(--muted-foreground)]">
                  No workspaces yet. Create one to upload documents and chat with AI.
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              {workspaces.map((ws) => (
                <Card key={ws.id}>
                  <CardContent className="pt-4">
                    <h3 className="font-medium">{ws.name}</h3>
                    <p className="mb-4 text-sm text-[var(--muted-foreground)]">
                      {ws.description || "No description"}
                    </p>
                    <div className="flex flex-wrap gap-2">
                      <Link href={`/documents?workspace_id=${ws.id}`}>
                        <Button variant="secondary" size="sm">
                          <FileText className="h-4 w-4" />
                          Documents
                        </Button>
                      </Link>
                      <Link href={`/chat?workspace_id=${ws.id}`}>
                        <Button size="sm">
                          <MessageSquare className="h-4 w-4" />
                          Chat
                        </Button>
                      </Link>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
