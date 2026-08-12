"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Users, UserPlus, Mail, Clock, Trash2, ArrowLeft, Activity } from "lucide-react";
import { orgApi, teamApi, activityApi, type Organization } from "@/lib/api";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Dialog } from "@/components/ui/Dialog";

/**
 * Single-org assumption, matching the rest of the app (useAllWorkspaces
 * flattens across orgs the same way): teams are managed for the first
 * organization the user belongs to.
 */
function useCurrentOrg() {
  return useQuery({
    queryKey: ["orgs", "current"],
    queryFn: async (): Promise<Organization | null> => {
      const orgs = await orgApi.list();
      return orgs.items[0] ?? null;
    },
  });
}

function roleBadgeVariant(role: string) {
  if (role === "owner") return "info" as const;
  if (role === "admin") return "success" as const;
  return "default" as const;
}

export default function TeamSettingsPage() {
  const queryClient = useQueryClient();
  const orgQuery = useCurrentOrg();
  const org = orgQuery.data;

  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"admin" | "member">("member");
  const [inviteError, setInviteError] = useState<string | null>(null);

  const membersQuery = useQuery({
    queryKey: ["team-members", org?.id],
    queryFn: () => teamApi.listMembers(org!.id),
    enabled: !!org,
  });

  const invitesQuery = useQuery({
    queryKey: ["team-invites", org?.id],
    queryFn: () => teamApi.listInvites(org!.id),
    enabled: !!org,
  });

  const activityQuery = useQuery({
    queryKey: ["team-activity", org?.id],
    queryFn: () => activityApi.list(org!.id),
    enabled: !!org,
  });

  const inviteMutation = useMutation({
    mutationFn: () => teamApi.createInvite(org!.id, inviteEmail, inviteRole),
    onSuccess: () => {
      setInviteOpen(false);
      setInviteEmail("");
      setInviteRole("member");
      setInviteError(null);
      queryClient.invalidateQueries({ queryKey: ["team-invites", org?.id] });
    },
    onError: (err: Error) => setInviteError(err.message),
  });

  const revokeMutation = useMutation({
    mutationFn: (inviteId: string) => teamApi.revokeInvite(org!.id, inviteId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["team-invites", org?.id] }),
  });

  const roleMutation = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: "admin" | "member" }) =>
      teamApi.updateMemberRole(org!.id, userId, role),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["team-members", org?.id] }),
  });

  const removeMutation = useMutation({
    mutationFn: (userId: string) => teamApi.removeMember(org!.id, userId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["team-members", org?.id] }),
  });

  const members = membersQuery.data?.items ?? [];
  const invites = invitesQuery.data?.items ?? [];
  const activity = activityQuery.data?.items ?? [];

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <Link
          href="/settings"
          className="mb-2 inline-flex items-center gap-1 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Settings
        </Link>
        <h1 className="text-2xl font-bold">Team</h1>
        <p className="text-sm text-[var(--muted-foreground)]">
          Manage who has access to {org?.name ?? "your organization"}
        </p>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Users className="h-5 w-5" />
              <h2 className="font-semibold">Members</h2>
            </div>
            <Button size="sm" onClick={() => setInviteOpen(true)} disabled={!org}>
              <UserPlus className="h-4 w-4" />
              Invite
            </Button>
          </div>
        </CardHeader>
        <CardContent className="divide-y divide-[var(--border)] p-0">
          {membersQuery.isLoading ? (
            <p className="p-4 text-sm text-[var(--muted-foreground)]">Loading...</p>
          ) : (
            members.map((member) => (
              <div
                key={member.user_id}
                className="flex items-center justify-between gap-3 p-4"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{member.full_name}</p>
                  <p className="truncate text-xs text-[var(--muted-foreground)]">{member.email}</p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <Badge variant={roleBadgeVariant(member.role)}>{member.role}</Badge>
                  {member.role !== "owner" && (
                    <>
                      <select
                        className="rounded-lg border border-[var(--border)] bg-transparent px-2 py-1 text-xs"
                        value={member.role}
                        onChange={(e) =>
                          roleMutation.mutate({
                            userId: member.user_id,
                            role: e.target.value as "admin" | "member",
                          })
                        }
                      >
                        <option value="member">member</option>
                        <option value="admin">admin</option>
                      </select>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => removeMutation.mutate(member.user_id)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </>
                  )}
                </div>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Mail className="h-5 w-5" />
            <h2 className="font-semibold">Pending Invites</h2>
          </div>
        </CardHeader>
        <CardContent className="divide-y divide-[var(--border)] p-0">
          {invites.length === 0 ? (
            <p className="p-4 text-sm text-[var(--muted-foreground)]">No pending invites.</p>
          ) : (
            invites.map((invite) => (
              <div key={invite.id} className="flex items-center justify-between gap-3 p-4">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{invite.email}</p>
                  <p className="text-xs text-[var(--muted-foreground)]">
                    Invited as {invite.role} · expires{" "}
                    {new Date(invite.expires_at).toLocaleDateString()}
                  </p>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => revokeMutation.mutate(invite.id)}
                >
                  Revoke
                </Button>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Activity className="h-5 w-5" />
            <h2 className="font-semibold">Recent Activity</h2>
          </div>
        </CardHeader>
        <CardContent className="divide-y divide-[var(--border)] p-0">
          {activity.length === 0 ? (
            <p className="p-4 text-sm text-[var(--muted-foreground)]">No activity yet.</p>
          ) : (
            activity.map((entry) => (
              <div key={entry.id} className="flex items-center gap-3 p-4">
                <Clock className="h-4 w-4 shrink-0 text-[var(--muted-foreground)]" />
                <p className="min-w-0 flex-1 truncate text-sm">
                  <span className="font-medium">{entry.actor_name ?? "Someone"}</span>{" "}
                  <span className="text-[var(--muted-foreground)]">{entry.action}</span>
                </p>
                <span className="shrink-0 text-xs text-[var(--muted-foreground)]">
                  {new Date(entry.created_at).toLocaleString()}
                </span>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      {inviteOpen && (
        <Dialog open onClose={() => setInviteOpen(false)} titleId="invite-title">
          <div className="p-6 space-y-4">
            <h3 id="invite-title" className="text-lg font-semibold">
              Invite a teammate
            </h3>
            <Input
              label="Email"
              type="email"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              placeholder="teammate@example.com"
            />
            <div className="space-y-1">
              <label className="block text-sm font-medium">Role</label>
              <select
                className="w-full rounded-lg border border-[var(--border)] bg-transparent px-4 py-2 text-sm"
                value={inviteRole}
                onChange={(e) => setInviteRole(e.target.value as "admin" | "member")}
              >
                <option value="member">Member</option>
                <option value="admin">Admin</option>
              </select>
            </div>
            {inviteError && <p className="text-xs text-[var(--destructive)]">{inviteError}</p>}
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setInviteOpen(false)}>
                Cancel
              </Button>
              <Button
                onClick={() => inviteMutation.mutate()}
                disabled={!inviteEmail || inviteMutation.isPending}
              >
                {inviteMutation.isPending ? "Sending..." : "Send invite"}
              </Button>
            </div>
          </div>
        </Dialog>
      )}
    </div>
  );
}
