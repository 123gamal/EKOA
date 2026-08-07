"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { Upload, FileText, Loader2, RefreshCw, CheckCircle2, AlertCircle, Layers } from "lucide-react";
import { documentApi, workspaceApi, type DocumentRecord, type Workspace } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Badge, statusBadgeVariant } from "@/components/ui/Badge";
import { Card, CardContent } from "@/components/ui/Card";

function DocumentsContent() {
  const searchParams = useSearchParams();
  const workspaceId = searchParams.get("workspace_id");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [docs, setDocs] = useState<DocumentRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");

  const loadDocs = useCallback(
    async (nextPage = 1, append = false) => {
      if (!workspaceId) return;
      try {
        const data = await documentApi.list(workspaceId, nextPage);
        setTotal(data.total);
        setPage(nextPage);
        setDocs((prev) => (append ? [...prev, ...data.items] : data.items));
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Failed to load documents");
      }
    },
    [workspaceId]
  );

  useEffect(() => {
    async function init() {
      try {
        const orgs = await fetch("/api/v1/organizations/", {
          headers: {
            Authorization: `Bearer ${localStorage.getItem("access_token")}`,
          },
        }).then((r) => r.json());

        const all: Workspace[] = [];
        if (orgs && Array.isArray(orgs.items)) {
          for (const org of orgs.items) {
            const ws = await workspaceApi.list(org.id);
            all.push(...ws.items);
          }
        }
        setWorkspaces(all);
      } catch {
        // ignore
      }
    }
    init();
  }, []);

  useEffect(() => {
    if (!workspaceId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    loadDocs().finally(() => setLoading(false));

    // Status poll: refresh page 1 in place and merge, so Load More pages are
    // preserved instead of being wiped by the 4s refresh.
    const interval = setInterval(() => {
      documentApi
        .list(workspaceId, 1)
        .then((data) => {
          setTotal(data.total);
          setDocs((prev) => {
            const page1Ids = new Set(data.items.map((d) => d.id));
            const older = prev.filter((d) => !page1Ids.has(d.id));
            return [...data.items, ...older];
          });
        })
        .catch(() => {
          // transient poll failure - keep the current list
        });
    }, 4000);

    return () => clearInterval(interval);
  }, [workspaceId, loadDocs]);

  async function loadMore() {
    if (loadingMore || !workspaceId) return;
    setLoadingMore(true);
    try {
      await loadDocs(page + 1, true);
    } finally {
      setLoadingMore(false);
    }
  }

  async function uploadFile(file: File) {
    if (!workspaceId) {
      setError("Please select a workspace first");
      return;
    }
    setUploading(true);
    setError("");
    setSuccessMsg("");
    try {
      const doc = await documentApi.upload(workspaceId, file);
      setDocs((prev) => [doc, ...prev]);
      setSuccessMsg(`"${file.name}" uploaded successfully and indexed into knowledge base!`);
      if (fileInputRef.current) fileInputRef.current.value = "";
      setTimeout(() => loadDocs(), 1500);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) uploadFile(file);
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Knowledge Base Documents</h1>
          <p className="text-sm text-[var(--muted-foreground)]">
            Upload enterprise documents to index into the Qdrant vector search engine for AI Agent retrieval
          </p>
        </div>
        {workspaces.length > 0 && (
          <select
            value={workspaceId || ""}
            onChange={(e) => {
              const id = e.target.value;
              if (id) window.location.href = `/documents?workspace_id=${id}`;
            }}
            className="rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
          >
            <option value="">Select workspace...</option>
            {workspaces.map((ws) => (
              <option key={ws.id} value={ws.id}>
                {ws.name}
              </option>
            ))}
          </select>
        )}
      </div>

      {!workspaceId ? (
        <Card className="border-dashed">
          <CardContent className="py-12 text-center">
            <FileText className="mx-auto mb-4 h-12 w-12 text-[var(--muted-foreground)]" />
            <h3 className="mb-2 text-lg font-semibold">No Workspace Selected</h3>
            <p className="mb-4 text-sm text-[var(--muted-foreground)]">
              Select a workspace from the dropdown above or go to your Dashboard to choose a knowledge workspace.
            </p>
            <Link href="/dashboard">
              <Button variant="secondary">Go to Dashboard</Button>
            </Link>
          </CardContent>
        </Card>
      ) : (
        <>
          <div
            onClick={() => !uploading && fileInputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            className={`cursor-pointer rounded-xl border-2 border-dashed p-8 text-center transition ${
              dragOver
                ? "border-[var(--primary)] bg-[var(--primary)]/5"
                : "border-[var(--border)] hover:border-[var(--primary)]/50 hover:bg-[var(--muted)]/50"
            }`}
          >
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-[var(--primary)]/10 text-[var(--primary)]">
              {uploading ? (
                <Loader2 className="h-6 w-6 animate-spin" />
              ) : (
                <Upload className="h-6 w-6" />
              )}
            </div>
            <h3 className="mb-1 text-base font-semibold">
              {uploading ? "Indexing Document..." : "Click or Drag & Drop File to Upload"}
            </h3>
            <p className="mb-3 text-xs text-[var(--muted-foreground)]">
              Supported Formats: PDF, DOCX, TXT, Markdown, CSV (Max 50MB)
            </p>
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              accept=".pdf,.docx,.doc,.txt,.md,.csv"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) uploadFile(file);
              }}
            />
            <Button
              type="button"
              variant="secondary"
              disabled={uploading}
              onClick={(e) => {
                e.stopPropagation();
                fileInputRef.current?.click();
              }}
            >
              {uploading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Processing...
                </>
              ) : (
                <>
                  <Upload className="h-4 w-4" />
                  Choose File
                </>
              )}
            </Button>
          </div>

          {error && (
            <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {successMsg && (
            <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              <span>{successMsg}</span>
            </div>
          )}

          <div className="flex items-center justify-between pt-2">
            <h2 className="text-lg font-semibold flex items-center gap-2">
              <Layers className="h-5 w-5 text-[var(--primary)]" />
              Workspace Documents ({total})
            </h2>
            <Button variant="ghost" size="sm" onClick={() => loadDocs()}>
              <RefreshCw className="h-4 w-4" />
              Refresh Status
            </Button>
          </div>

          {loading ? (
            <div className="flex justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-[var(--muted-foreground)]" />
            </div>
          ) : docs.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center text-[var(--muted-foreground)]">
                No documents uploaded to this workspace yet. Upload a file above to begin indexing.
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-3">
              {docs.map((doc) => (
                <Card key={doc.id} className="transition hover:shadow-sm">
                  <CardContent className="flex items-center justify-between py-4">
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="flex items-center gap-2">
                        <FileText className="h-4 w-4 text-[var(--primary)] shrink-0" />
                        <h3 className="truncate font-medium">{doc.title}</h3>
                      </div>
                      <p className="text-xs text-[var(--muted-foreground)]">
                        {doc.content_type} &middot; Uploaded {new Date(doc.created_at).toLocaleString()}
                        {doc.chunk_count != null && doc.chunk_count > 0 && (
                          <span className="ml-2 font-medium text-emerald-600">
                            &middot; {doc.chunk_count} vector chunks indexed
                          </span>
                        )}
                      </p>
                    </div>
                    <Badge variant={statusBadgeVariant(doc.status)}>
                      {doc.status}
                    </Badge>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
          {docs.length > 0 && docs.length < total && (
            <div className="flex justify-center pt-2">
              <Button variant="secondary" size="sm" onClick={loadMore} disabled={loadingMore}>
                {loadingMore ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )}
                Load More ({docs.length} of {total})
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default function DocumentsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex justify-center py-24">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      }
    >
      <DocumentsContent />
    </Suspense>
  );
}
