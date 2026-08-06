import { Loader2 } from "lucide-react";

export default function Loading() {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-24">
      <div className="rounded-full bg-[var(--primary)]/10 p-4 text-[var(--primary)]">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
      <p className="text-sm text-[var(--muted-foreground)]">Loading workspace...</p>
    </div>
  );
}
