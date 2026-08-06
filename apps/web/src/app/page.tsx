import Link from "next/link";
import {
  Brain,
  FileSearch,
  Shield,
  Zap,
} from "lucide-react";

const features = [
  {
    icon: Brain,
    title: "Multi-Agent AI",
    description:
      "LangGraph-powered agents coordinate retrieval, analysis, and synthesis.",
  },
  {
    icon: FileSearch,
    title: "Enterprise RAG",
    description:
      "Upload documents and get citation-backed answers from your knowledge base.",
  },
  {
    icon: Shield,
    title: "Secure by Design",
    description:
      "JWT authentication, RBAC, audit logging, and multi-tenant isolation.",
  },
  {
    icon: Zap,
    title: "Workflow Automation",
    description:
      "Automate repetitive tasks with human-in-the-loop approval workflows.",
  },
];

export default function HomePage() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-[var(--border)]">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-2 font-bold text-lg">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--primary)] text-[var(--primary-foreground)] text-sm">
              E
            </span>
            EKOA
          </div>
          <div className="flex gap-3">
            <Link
              href="/login"
              className="rounded-lg px-4 py-2 text-sm font-medium hover:bg-[var(--muted)]"
            >
              Sign In
            </Link>
            <Link
              href="/register"
              className="rounded-lg bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] hover:opacity-90"
            >
              Get Started
            </Link>
          </div>
        </div>
      </header>

      <main>
        <section className="mx-auto max-w-6xl px-6 py-20 text-center">
          <h1 className="mb-4 text-4xl font-bold tracking-tight sm:text-5xl">
            Enterprise Knowledge
            <br />
            <span className="text-[var(--primary)]">Operations Assistant</span>
          </h1>
          <p className="mx-auto mb-8 max-w-2xl text-lg text-[var(--muted-foreground)]">
            AI-first platform combining RAG, multi-agent orchestration, and
            enterprise-grade security for your organization&apos;s knowledge.
          </p>
          <div className="flex justify-center gap-4">
            <Link
              href="/register"
              className="rounded-lg bg-[var(--primary)] px-8 py-3 font-medium text-[var(--primary-foreground)] hover:opacity-90"
            >
              Start Free
            </Link>
            <Link
              href="/login"
              className="rounded-lg border border-[var(--border)] px-8 py-3 font-medium hover:bg-[var(--muted)]"
            >
              Sign In
            </Link>
          </div>
        </section>

        <section className="border-t border-[var(--border)] bg-[var(--muted)]/30 py-16">
          <div className="mx-auto grid max-w-6xl gap-8 px-6 sm:grid-cols-2 lg:grid-cols-4">
            {features.map(({ icon: Icon, title, description }) => (
              <div key={title} className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-6">
                <Icon className="mb-3 h-8 w-8 text-[var(--primary)]" />
                <h3 className="mb-2 font-semibold">{title}</h3>
                <p className="text-sm text-[var(--muted-foreground)]">{description}</p>
              </div>
            ))}
          </div>
        </section>
      </main>

      <footer className="border-t border-[var(--border)] py-6 text-center text-sm text-[var(--muted-foreground)]">
        EKOA &mdash; Enterprise Software Architecture Specification v1.0
      </footer>
    </div>
  );
}
