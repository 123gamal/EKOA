"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { Bot, User, Send, Loader2, Sparkles, FileText, Compass, Layers } from "lucide-react";
import { getAccessToken } from "@/lib/auth";
import { consumeSSE } from "@/lib/sse";
import { workspaceApi, type Workspace } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Card, CardContent } from "@/components/ui/Card";

interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: string[];
  degraded?: boolean;
}

interface AgentActivity {
  agent: string;
  action: string;
  output: string;
}

const SUGGESTED_PROMPTS = [
  "What is the main architecture of EKOA?",
  "Summarize key information in the knowledge base",
  "How do vector embeddings work in Qdrant?",
  "List available API endpoints",
];

function ChatContent() {
  const searchParams = useSearchParams();
  const workspaceId = searchParams.get("workspace_id");

  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [agents, setAgents] = useState<AgentActivity[]>([]);
  const [error, setError] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, agents, sending]);

  useEffect(() => {
    async function loadWorkspaces() {
      try {
        const orgs = await fetch("/api/v1/organizations/", {
          headers: { Authorization: `Bearer ${getAccessToken()}` },
        }).then((r) => r.json());

        const all: Workspace[] = [];
        if (Array.isArray(orgs)) {
          for (const org of orgs) {
            const ws = await workspaceApi.list(org.id);
            all.push(...ws);
          }
        }
        setWorkspaces(all);
      } catch {
        // ignore
      }
    }
    loadWorkspaces();
  }, []);

  const sendMessage = useCallback(async (customText?: string) => {
    const textToSend = (customText || input).trim();
    if (!textToSend || !workspaceId) return;
    const token = getAccessToken();
    if (!token) return;

    const userMsg: Message = { role: "user", content: textToSend };
    setMessages((prev) => [...prev, userMsg]);
    if (!customText) setInput("");
    setSending(true);
    setAgents([]);
    setError("");

    const history = messages.map((m) => ({ role: m.role, content: m.content }));

    try {
      const res = await fetch("/api/v1/ai/chat/stream", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          workspace_id: workspaceId,
          message: userMsg.content,
          history,
        }),
      });

      if (!res.ok) throw new Error("Stream request failed");

      let assistantAdded = false;

      await consumeSSE(res, (event, data) => {
        if (event === "agent_start" || event === "agent_action") {
          setAgents((prev) => [
            ...prev,
            {
              agent: String(data.agent || "agent"),
              action: String(data.action || event),
              output: String(data.output || ""),
            },
          ]);
        }

        if (event === "message") {
          const reply = String(data.reply || "");
          const sources = Array.isArray(data.sources)
            ? (data.sources as string[])
            : [];
          const degraded = Boolean(data.degraded);

          if (!assistantAdded) {
            assistantAdded = true;
            setMessages((prev) => [
              ...prev,
              { role: "assistant", content: reply, sources, degraded },
            ]);
          } else {
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last?.role === "assistant") {
                updated[updated.length - 1] = {
                  ...last,
                  content: reply,
                  sources,
                  degraded,
                };
              }
              return updated;
            });
          }
        }
      });
    } catch {
      setError("Failed to get a response. Make sure the AI service is running.");
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content:
            "Sorry, an error occurred while processing your request. Ensure the AI service is running on port 8001.",
        },
      ]);
    } finally {
      setSending(false);
    }
  }, [input, workspaceId, messages]);

  return (
    <div className="mx-auto flex h-[calc(100vh-8rem)] max-w-5xl flex-col space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Sparkles className="h-6 w-6 text-[var(--primary)]" />
            RAG AI Assistant
          </h1>
          <p className="text-sm text-[var(--muted-foreground)]">
            Multi-Agent LangGraph Orchestrator with Qdrant Vector Retrieval
          </p>
        </div>
        {workspaces.length > 0 && (
          <select
            value={workspaceId || ""}
            onChange={(e) => {
              const id = e.target.value;
              if (id) window.location.href = `/chat?workspace_id=${id}`;
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
        <Card className="flex flex-1 items-center justify-center border-dashed">
          <CardContent className="text-center py-12">
            <Bot className="mx-auto mb-4 h-12 w-12 text-[var(--muted-foreground)]" />
            <h3 className="text-lg font-semibold mb-2">No Workspace Selected</h3>
            <p className="mb-4 text-sm text-[var(--muted-foreground)]">
              Select a workspace above or go to your Dashboard to begin chatting with your indexed documents.
            </p>
            <Link href="/dashboard">
              <Button variant="secondary">Go to Dashboard</Button>
            </Link>
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="flex-1 space-y-4 overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-inner">
            {messages.length === 0 && (
              <div className="flex flex-col items-center justify-center py-12 text-center space-y-4">
                <div className="rounded-full bg-[var(--primary)]/10 p-4 text-[var(--primary)]">
                  <Compass className="h-8 w-8" />
                </div>
                <div>
                  <h3 className="font-semibold text-base">Ask Anything About Your Knowledge Base</h3>
                  <p className="text-xs text-[var(--muted-foreground)] max-w-sm mt-1">
                    Select a prompt below or type your question to trigger Multi-Agent retrieval & synthesis
                  </p>
                </div>
                <div className="flex flex-wrap justify-center gap-2 max-w-lg pt-2">
                  {SUGGESTED_PROMPTS.map((prompt, idx) => (
                    <button
                      key={idx}
                      onClick={() => sendMessage(prompt)}
                      className="rounded-full border border-[var(--border)] bg-[var(--muted)]/50 px-3 py-1.5 text-xs text-[var(--foreground)] hover:border-[var(--primary)] hover:bg-[var(--primary)]/10 transition"
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((msg, i) => (
              <div
                key={i}
                className={`flex gap-3 ${msg.role === "user" ? "flex-row-reverse" : ""}`}
              >
                <div
                  className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
                    msg.role === "user"
                      ? "bg-[var(--primary)] text-[var(--primary-foreground)] font-bold text-xs"
                      : "bg-[var(--muted)] text-[var(--foreground)]"
                  }`}
                >
                  {msg.role === "user" ? (
                    <User className="h-4 w-4" />
                  ) : (
                    <Bot className="h-4 w-4" />
                  )}
                </div>
                <div
                  className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                    msg.role === "user"
                      ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                      : "bg-[var(--muted)]/80 text-[var(--foreground)] border border-[var(--border)]"
                  }`}
                >
                  <p className="whitespace-pre-wrap">{msg.content}</p>
                  {msg.degraded && (
                    <div className="mt-3 rounded-lg border border-[var(--warning)]/40 bg-[var(--warning)]/10 px-3 py-2 text-xs text-[var(--warning)]">
                      <strong>AI temporarily unavailable:</strong> no configured LLM
                      provider responded, so EKOA returned a local template answer
                      instead. Check API keys or retry shortly.
                    </div>
                  )}
                  {msg.sources && msg.sources.length > 0 && (
                    <div className="mt-3 border-t border-[var(--border)]/50 pt-2">
                      <p className="mb-1 text-xs font-semibold opacity-75 flex items-center gap-1">
                        <FileText className="h-3 w-3" /> Source Document Citations
                      </p>
                      <div className="flex flex-wrap gap-1">
                        {msg.sources.map((src) => (
                          <Badge key={src} variant="info" className="text-[10px]">
                            Doc ID: {src.slice(0, 8)}...
                          </Badge>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            ))}

            {agents.length > 0 && (
              <div className="flex flex-wrap gap-2 justify-center py-2">
                {agents.map((a, i) => (
                  <Badge
                    key={i}
                    variant="info"
                    title={`${a.action}: ${a.output}`}
                    className="text-xs py-1 px-2.5"
                  >
                    <Layers className="mr-1 h-3 w-3 inline" />
                    {a.agent}: {a.action}
                  </Badge>
                ))}
              </div>
            )}

            {sending && (
              <div className="flex items-center gap-2 text-xs text-[var(--muted-foreground)] py-2">
                <Loader2 className="h-4 w-4 animate-spin text-[var(--primary)]" />
                <span>Multi-Agent LangGraph orchestrating response...</span>
              </div>
            )}

            <div ref={bottomRef} />
          </div>

          {error && (
            <p className="text-xs text-red-500 font-medium px-1">{error}</p>
          )}

          <div className="flex gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && !sending && sendMessage()}
              placeholder="Ask a question about your knowledge base..."
              disabled={sending}
              className="flex-1 rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
            />
            <Button onClick={() => sendMessage()} disabled={sending || !input.trim()}>
              {sending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
              Send
            </Button>
          </div>
        </>
      )}
    </div>
  );
}

export default function ChatPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center py-24">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      }
    >
      <ChatContent />
    </Suspense>
  );
}
