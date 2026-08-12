"use client";

import { Suspense, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { motion } from "motion/react";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Upload, FileText, Loader2, RefreshCw, CheckCircle2, AlertCircle, Layers } from "lucide-react";
import { documentApi, type DocumentRecord } from "@/lib/api";
import { useAllWorkspaces } from "@/lib/queries";
import { Button } from "@/components/ui/Button";
import { Badge, statusBadgeVariant } from "@/components/ui/Badge";
import { Card, CardContent } from "@/components/ui/Card";
import { staggerContainer, staggerItem } from "@/components/ui/motion";

const POLL_INTERVAL_MS = 4000;
const PAGE_SIZE = 25;

function DocumentsContent() {
  const searchParams = useSearchParams();
  const workspaceId = searchParams.get("workspace_id");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();

  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");

  const workspacesQuery = useAllWorkspaces();
  const workspaces = workspacesQuery.data ?? [];

  const docsQuery = useInfiniteQuery({
    queryKey: ["documents", workspaceId ?? null],
    queryFn: ({ pageParam }) => documentApi.list(workspaceId!, pageParam, PAGE_SIZE),
    enabled: !!workspaceId,
    initialPageParam: 1,
    getNextPageParam: (lastPage) =>
      lastPage.page < lastPage.pages ? lastPage.page + 1 : undefined,
    // Status poll: refresh the fetched pages in place at the same cadence the
    // manual implementation used, so PROCESSING -> INDEXED appears live.
    refetchInterval: workspaceId ? POLL_INTERVAL_MS : false,
  });

  const docs = docsQuery.data?.pages.flatMap((p) => p.items) ?? [];
  const total = docsQuery.data?.pages[0]?.total ?? 0;

  const uploadMutation = useMutation({
    mutationFn: ({ workspaceId: wsId, file }: { workspaceId: string; file: File }) =>
      documentApi.upload(wsId, file),
    onSuccess: (doc) => {
      setSuccessMsg(`"${doc.title}" uploaded successfully and indexed into knowledge base!`);
      if (fileInputRef.current) fileInputRef.current.value = "";
      queryClient.invalidateQueries({ queryKey: ["documents", workspaceId ?? null] });
    },
    onError: (e: unknown) => {
      setError(e instanceof Error ? e.message : "Upload failed");
    },
  });

  async function uploadFile(file: File) {
    if (!workspaceId) {
      setError("Please select a workspace first");
      return;
    }
    setUploading(true);
    setError("");
    setSuccessMsg("");
    try {
      await uploadMutation.mutateAsync({ workspaceId, file });
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
            <div
              role="alert"
              className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
            >
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
            <Button
              variant="ghost"
              size="sm"
              onClick={() =>
                queryClient.invalidateQueries({ queryKey: ["documents", workspaceId ?? null] })
              }
            >
              <RefreshCw className="h-4 w-4" />
              Refresh Status
            </Button>
          </div>

          {docsQuery.isLoading ? (
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
            <motion.div variants={staggerContainer} initial="initial" animate="animate" className="space-y-3">
              {docs.map((doc) => (
                <motion.div key={doc.id} variants={staggerItem}>
                  <Card>
                    <CardContent className="flex items-center justify-between py-4">
                      <div className="min-w-0 flex-1 space-y-1">
                        <div className="flex items-center gap-2">
                          <FileText className="h-4 w-4 text-[var(--primary)] shrink-0" />
                          <h3 className="truncate font-medium">{doc.title}</h3>
                        </div>
                        <p className="text-xs text-[var(--muted-foreground)]">
                          {doc.content_type} &middot; Uploaded {new Date(doc.created_at).toLocaleString()}
                          {doc.chunk_count != null && doc.chunk_count > 0 && (
                            <span className="ml-2 font-medium text-[var(--success)]">
                              &middot; {doc.chunk_count} vector chunks indexed
                            </span>
                          )}
                        </p>
                      </div>
                      <Badge
                        variant={statusBadgeVariant(doc.status)}
                        animated={doc.status === "PROCESSING" || doc.status === "PENDING"}
                      >
                        {doc.status}
                      </Badge>
                    </CardContent>
                  </Card>
                </motion.div>
              ))}
            </motion.div>
          )}
          {docs.length > 0 && docs.length < total && (
            <div className="flex justify-center pt-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => docsQuery.fetchNextPage()}
                disabled={docsQuery.isFetchingNextPage || !docsQuery.hasNextPage}
              >
                {docsQuery.isFetchingNextPage ? (
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
