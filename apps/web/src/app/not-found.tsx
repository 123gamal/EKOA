import Link from "next/link";
import { FileQuestion } from "lucide-react";
import { Button } from "@/components/ui/Button";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-md space-y-4 py-24 text-center">
      <FileQuestion className="mx-auto h-12 w-12 text-[var(--muted-foreground)]" />
      <h1 className="text-2xl font-bold">Page Not Found</h1>
      <p className="text-sm text-[var(--muted-foreground)]">
        The page you are looking for does not exist.
      </p>
      <Link href="/dashboard">
        <Button>Back to Dashboard</Button>
      </Link>
    </div>
  );
}
