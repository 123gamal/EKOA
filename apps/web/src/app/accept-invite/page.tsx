"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { CheckCircle2, XCircle } from "lucide-react";
import { getAccessToken } from "@/lib/auth";
import { teamApi } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";

type Status = "checking" | "accepting" | "success" | "error";

function AcceptInviteInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");
  const [status, setStatus] = useState<Status>("checking");
  const [message, setMessage] = useState<string>("");

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setMessage("This invite link is missing its token.");
      return;
    }

    if (!getAccessToken()) {
      // Not logged in yet: send through login, then come straight back here.
      const redirect = encodeURIComponent(`/accept-invite?token=${token}`);
      router.replace(`/login?redirect=${redirect}`);
      return;
    }

    setStatus("accepting");
    teamApi
      .acceptInvite(token)
      .then(() => setStatus("success"))
      .catch((err: Error) => {
        setStatus("error");
        setMessage(err.message);
      });
  }, [token, router]);

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardContent className="flex flex-col items-center gap-4 py-10 text-center">
          {(status === "checking" || status === "accepting") && (
            <p className="text-sm text-[var(--muted-foreground)]">Accepting invite...</p>
          )}
          {status === "success" && (
            <>
              <CheckCircle2 className="h-12 w-12 text-[var(--success)]" />
              <h1 className="text-lg font-semibold">You're in!</h1>
              <p className="text-sm text-[var(--muted-foreground)]">
                You've joined the organization. Head to your dashboard to get started.
              </p>
              <Button onClick={() => router.push("/dashboard")}>Go to dashboard</Button>
            </>
          )}
          {status === "error" && (
            <>
              <XCircle className="h-12 w-12 text-[var(--destructive)]" />
              <h1 className="text-lg font-semibold">Couldn't accept invite</h1>
              <p className="text-sm text-[var(--muted-foreground)]">{message}</p>
              <Button variant="secondary" onClick={() => router.push("/dashboard")}>
                Go to dashboard
              </Button>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default function AcceptInvitePage() {
  return (
    <Suspense>
      <AcceptInviteInner />
    </Suspense>
  );
}
