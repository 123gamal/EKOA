"use client";

import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/Button";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="mx-auto max-w-md space-y-4 py-20 text-center">
      <AlertTriangle className="mx-auto h-10 w-10 text-red-500" />
      <h1 className="text-xl font-bold">Something went wrong</h1>
      <p className="text-sm text-[var(--muted-foreground)]">
        {error.message || "An unexpected error occurred while rendering this page."}
      </p>
      <Button onClick={reset}>Try Again</Button>
    </div>
  );
}
