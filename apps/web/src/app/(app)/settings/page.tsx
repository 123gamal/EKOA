"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Settings, User, Plug, Users, ChevronRight } from "lucide-react";
import { authApi, type UserProfile } from "@/lib/api";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { GitHubConnectorPanel } from "@/components/integrations/GitHubConnectorPanel";
import { useAllWorkspaces } from "@/lib/queries";

export default function SettingsPage() {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);

  const workspacesQuery = useAllWorkspaces();
  const workspaces = workspacesQuery.data ?? [];

  useEffect(() => {
    authApi
      .me()
      .then(setUser)
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Settings</h1>
        <p className="text-sm text-[var(--muted-foreground)]">
          Account and platform preferences
        </p>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <User className="h-5 w-5" />
            <h2 className="font-semibold">Profile</h2>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <p className="text-sm text-[var(--muted-foreground)]">Loading...</p>
          ) : user ? (
            <dl className="grid gap-4 sm:grid-cols-2">
              <div>
                <dt className="text-xs text-[var(--muted-foreground)]">Full Name</dt>
                <dd className="font-medium">{user.full_name}</dd>
              </div>
              <div>
                <dt className="text-xs text-[var(--muted-foreground)]">Email</dt>
                <dd className="font-medium">{user.email}</dd>
              </div>
              <div>
                <dt className="text-xs text-[var(--muted-foreground)]">Status</dt>
                <dd>
                  <Badge variant={user.is_active ? "success" : "error"}>
                    {user.is_active ? "Active" : "Inactive"}
                  </Badge>
                </dd>
              </div>
              <div>
                <dt className="text-xs text-[var(--muted-foreground)]">Member Since</dt>
                <dd className="font-medium">
                  {new Date(user.created_at).toLocaleDateString()}
                </dd>
              </div>
            </dl>
          ) : (
            <p className="text-sm text-red-500">Failed to load profile</p>
          )}
        </CardContent>
      </Card>

      <Link href="/settings/team">
        <Card className="transition-colors hover:border-[var(--primary)]/40">
          <CardContent className="flex items-center justify-between py-4">
            <div className="flex items-center gap-2">
              <Users className="h-5 w-5" />
              <div>
                <h2 className="font-semibold">Team</h2>
                <p className="text-xs text-[var(--muted-foreground)]">
                  Invite teammates and manage roles
                </p>
              </div>
            </div>
            <ChevronRight className="h-4 w-4 text-[var(--muted-foreground)]" />
          </CardContent>
        </Card>
      </Link>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Plug className="h-5 w-5" />
            <h2 className="font-semibold">Integrations</h2>
          </div>
        </CardHeader>
        <CardContent>
          <GitHubConnectorPanel workspaces={workspaces} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Settings className="h-5 w-5" />
            <h2 className="font-semibold">Platform Features</h2>
          </div>
        </CardHeader>
        <CardContent>
          <ul className="space-y-2 text-sm text-[var(--muted-foreground)]">
            <li>OAuth providers (Google, Microsoft, GitHub) — planned (FR-101/102)</li>
            <li>Password reset & email verification — planned (FR-104/105)</li>
            <li>Session management — planned (FR-106)</li>
            <li>AI provider management — planned (FR-900)</li>
            <li>Enterprise integrations — GitHub connector available; more planned (FR-700)</li>
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
