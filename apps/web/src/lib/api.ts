import { setTokens, clearTokens } from "@/lib/auth";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

// Endpoints that must never trigger the silent refresh loop: /auth/login 401s
// on bad credentials, /auth/refresh and /auth/logout manage the token itself.
const NO_REFRESH_PATHS = ["/auth/login", "/auth/refresh", "/auth/logout"];

export interface UserProfile {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  is_superuser: boolean;
  created_at: string;
  updated_at: string;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  description?: string | null;
  owner_id: string;
  created_at: string;
  updated_at: string;
}

export interface Workspace {
  id: string;
  name: string;
  description?: string | null;
  organization_id: string;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface DocumentRecord {
  id: string;
  title: string;
  content_type: string;
  status: "PENDING" | "PROCESSING" | "INDEXED" | "FAILED";
  chunk_count: number;
  source_url?: string | null;
  workspace_id: string;
  uploaded_by: string;
  created_at: string;
  updated_at: string;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface WorkflowTemplate {
  id: string;
  title: string;
  description: string;
  category: string;
  steps: { id: string; name: string; type: string }[];
}

export interface Workflow {
  id: string;
  name: string;
  description?: string | null;
  template_id: string;
  status: "DRAFT" | "PENDING" | "RUNNING" | "AWAITING_APPROVAL" | "COMPLETED" | "FAILED" | "REJECTED";
  workspace_id: string;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface WorkflowStepResult {
  id: string;
  name: string;
  type: string;
  status: "idle" | "running" | "completed" | "failed" | "pending_approval" | "approved" | "rejected";
  output: string;
  duration_ms?: number;
  data?: Record<string, unknown>;
}

export interface WorkflowRun {
  id: string;
  workflow_id: string;
  status: "PENDING" | "RUNNING" | "AWAITING_APPROVAL" | "COMPLETED" | "FAILED" | "REJECTED";
  steps: WorkflowStepResult[] | null;
  logs: { ts: string; level: string; message: string }[] | null;
  error?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  approval_status?: string | null;
  approval_step_id?: string | null;
  approved_by?: string | null;
  approved_at?: string | null;
  approval_reason?: string | null;
  created_at: string;
}

export interface AnalyticsOverview {
  organizations: number;
  workspaces: number;
  documents: number;
  documents_by_status: Record<string, number>;
  chunks: number;
  success_rate: number;
  workflow_runs: Record<string, number>;
  uploads_last_7_days: { date: string; count: number }[];
  recent_runs: {
    workflow_id: string;
    status: string;
    started_at?: string | null;
    completed_at?: string | null;
  }[];
  recent_activity: {
    action: string;
    resource_type?: string | null;
    details?: Record<string, unknown> | null;
    created_at: string;
  }[];
}

// Model performance is computed from ai_call_logs telemetry (FR-1000).
export interface ModelPerformanceSummary {
  calls: number;
  avg_latency_ms: number | null;
  p95_latency_ms: number | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  degraded_rate: number;
  guardrail_trigger_rate: number;
  citation_drop_rate: number;
  est_cost_usd: number;
  cost_is_estimate: boolean;
  providers: Record<string, number>;
}

export interface ModelPerformanceDaily {
  date: string;
  calls: number;
  avg_latency_ms: number | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  est_cost_usd: number;
}

export interface ModelPerformanceCall {
  id: string;
  provider: string | null;
  model: string | null;
  latency_ms: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  degraded: boolean;
  guardrail_triggered: boolean;
  citations_dropped: boolean;
  cost_estimate: number | null;
  workspace_id: string;
  created_at: string;
}

export interface ModelPerformanceResponse {
  summary: ModelPerformanceSummary;
  daily: ModelPerformanceDaily[];
  recent_calls: Paginated<ModelPerformanceCall>;
}

export interface Connector {
  id: string;
  organization_id: string;
  workspace_id: string;
  provider: string;
  name: string;
  status: "connected" | "error" | "disconnected";
  status_reason?: string | null;
  connected_by: string;
  connected_at?: string | null;
  last_sync_at?: string | null;
  last_sync_status?: "success" | "failed" | "running" | null;
  last_sync_error?: string | null;
  last_sync_document_count?: number | null;
  config?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface OrgMemberRecord {
  user_id: string;
  email: string;
  full_name: string;
  role: "owner" | "admin" | "member";
  joined_at: string;
}

export interface OrgInviteRecord {
  id: string;
  organization_id: string;
  email: string;
  role: string;
  status: "pending" | "accepted" | "revoked";
  invited_by: string;
  expires_at: string;
  accepted_at?: string | null;
  created_at: string;
}

export interface ActivityEntry {
  id: string;
  user_id?: string | null;
  actor_name?: string | null;
  actor_email?: string | null;
  action: string;
  resource_type?: string | null;
  resource_id?: string | null;
  details?: Record<string, unknown> | null;
  created_at: string;
}

export interface Notification {
  id: string;
  type: string;
  title: string;
  body?: string | null;
  resource_type?: string | null;
  resource_id?: string | null;
  read_at?: string | null;
  created_at: string;
}

export interface ConnectorHealth {
  id: string;
  provider: string;
  name: string;
  status: "connected" | "error" | "disconnected";
  token_valid: boolean;
  detail: string;
  last_sync_at?: string | null;
  last_sync_status?: "success" | "failed" | "running" | null;
  last_sync_error?: string | null;
}

let refreshPromise: Promise<boolean> | null = null;

/**
 * Rotate the refresh token (sent automatically from its HttpOnly cookie) for a
 * fresh access token. Concurrency-safe: concurrent 401s share one request.
 */
async function refreshAccessToken(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = fetch(`${API_BASE_URL}/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    })
      .then(async (res) => {
        if (res.ok) {
          const data = (await res.json()) as Partial<TokenPair>;
          if (data.access_token) {
            setTokens(data.access_token);
            return true;
          }
        }
        return false;
      })
      .catch(() => false)
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

export async function apiFetch(
  endpoint: string,
  options: RequestInit = {},
  retried = false
) {
  const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  if (!(options.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    headers,
    credentials: "include",
  });

  if (
    response.status === 401 &&
    typeof window !== "undefined" &&
    !retried &&
    !NO_REFRESH_PATHS.some((p) => endpoint.startsWith(p))
  ) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      return apiFetch(endpoint, options, true);
    }
    clearTokens();
    if (window.location.pathname !== "/login") {
      const redirect = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.href = `/login?redirect=${redirect}`;
    }
  }

  return response;
}

/**
 * FastAPI error bodies aren't always `{ detail: string }` — a 422 validation
 * error returns `detail` as an array of Pydantic error objects
 * (`{loc, msg, type}[]`). Throwing that raw shape as an Error's message
 * renders as "[object Object]" in the UI; this normalizes every shape to a
 * readable string.
 */
async function extractErrorDetail(res: Response, fallback: string): Promise<string> {
  let body: unknown;
  try {
    body = await res.json();
  } catch {
    return fallback;
  }
  const detail = (body as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map((e) =>
        e && typeof e === "object" && "msg" in e ? String((e as { msg: unknown }).msg) : String(e)
      )
      .join("; ");
  }
  return fallback;
}

export const authApi = {
  async register(data: { email: string; password: string; full_name: string }): Promise<UserProfile> {
    const res = await apiFetch("/auth/register", { method: "POST", body: JSON.stringify(data) });
    if (!res.ok) throw new Error(await extractErrorDetail(res, "Registration failed"));
    return res.json();
  },
  async login(data: { email: string; password: string }): Promise<TokenPair> {
    const res = await apiFetch("/auth/login", { method: "POST", body: JSON.stringify(data) });
    if (!res.ok) throw new Error(await extractErrorDetail(res, "Login failed"));
    return res.json();
  },
  async getMe(): Promise<UserProfile> {
    const res = await apiFetch("/auth/me");
    if (!res.ok) throw new Error(await extractErrorDetail(res, "Failed to fetch profile"));
    return res.json();
  },
  async me(): Promise<UserProfile> {
    return this.getMe();
  },
  async logout(refreshToken?: string): Promise<void> {
    // The refresh token is now read from the HttpOnly cookie server-side;
    // the body arg is accepted for backwards compatibility only.
    const body = refreshToken ? { refresh_token: refreshToken } : {};
    await apiFetch("/auth/logout", { method: "POST", body: JSON.stringify(body) });
  },
};

export const orgApi = {
  async list(page = 1, pageSize = 25): Promise<Paginated<Organization>> {
    const res = await apiFetch(`/organizations/?page=${page}&page_size=${pageSize}`);
    if (!res.ok) throw new Error("Failed to list organizations");
    return res.json();
  },
  async create(data: { name: string; slug: string; description?: string }): Promise<Organization> {
    const res = await apiFetch("/organizations/", { method: "POST", body: JSON.stringify(data) });
    if (!res.ok) throw new Error(await extractErrorDetail(res, "Failed to create organization"));
    return res.json();
  },
  async getBySlug(slug: string): Promise<Organization> {
    const res = await apiFetch(`/organizations/${slug}`);
    if (!res.ok) throw new Error("Organization not found");
    return res.json();
  },
};

export const teamApi = {
  async listMembers(orgId: string, page = 1, pageSize = 50): Promise<Paginated<OrgMemberRecord>> {
    const res = await apiFetch(`/organizations/${orgId}/members?page=${page}&page_size=${pageSize}`);
    if (!res.ok) throw new Error(await extractErrorDetail(res, "Failed to list members"));
    return res.json();
  },
  async updateMemberRole(orgId: string, userId: string, role: "admin" | "member"): Promise<OrgMemberRecord> {
    const res = await apiFetch(`/organizations/${orgId}/members/${userId}`, {
      method: "PATCH",
      body: JSON.stringify({ role }),
    });
    if (!res.ok) throw new Error(await extractErrorDetail(res, "Failed to update member role"));
    return res.json();
  },
  async removeMember(orgId: string, userId: string): Promise<void> {
    const res = await apiFetch(`/organizations/${orgId}/members/${userId}`, { method: "DELETE" });
    if (!res.ok) throw new Error(await extractErrorDetail(res, "Failed to remove member"));
  },
  async listInvites(orgId: string): Promise<Paginated<OrgInviteRecord>> {
    const res = await apiFetch(`/organizations/${orgId}/invites`);
    if (!res.ok) throw new Error(await extractErrorDetail(res, "Failed to list invites"));
    return res.json();
  },
  async createInvite(orgId: string, email: string, role: "admin" | "member"): Promise<OrgInviteRecord> {
    const res = await apiFetch(`/organizations/${orgId}/invites`, {
      method: "POST",
      body: JSON.stringify({ email, role }),
    });
    if (!res.ok) throw new Error(await extractErrorDetail(res, "Failed to send invite"));
    return res.json();
  },
  async revokeInvite(orgId: string, inviteId: string): Promise<void> {
    const res = await apiFetch(`/organizations/${orgId}/invites/${inviteId}`, { method: "DELETE" });
    if (!res.ok) throw new Error(await extractErrorDetail(res, "Failed to revoke invite"));
  },
  async acceptInvite(token: string): Promise<OrgInviteRecord> {
    const res = await apiFetch("/invites/accept", {
      method: "POST",
      body: JSON.stringify({ token }),
    });
    if (!res.ok) throw new Error(await extractErrorDetail(res, "Failed to accept invite"));
    return res.json();
  },
};

export const activityApi = {
  async list(orgId: string, page = 1, pageSize = 25): Promise<Paginated<ActivityEntry>> {
    const res = await apiFetch(`/organizations/${orgId}/activity?page=${page}&page_size=${pageSize}`);
    if (!res.ok) throw new Error(await extractErrorDetail(res, "Failed to load activity"));
    return res.json();
  },
};

export const notificationApi = {
  async list(unreadOnly = false, page = 1, pageSize = 10): Promise<Paginated<Notification>> {
    const res = await apiFetch(
      `/notifications/?unread_only=${unreadOnly}&page=${page}&page_size=${pageSize}`
    );
    if (!res.ok) throw new Error("Failed to load notifications");
    return res.json();
  },
  async unreadCount(): Promise<number> {
    const res = await apiFetch("/notifications/unread-count");
    if (!res.ok) throw new Error("Failed to load unread notification count");
    const data = await res.json();
    return data.unread_count;
  },
  async markRead(id: string): Promise<Notification> {
    const res = await apiFetch(`/notifications/${id}/read`, { method: "POST" });
    if (!res.ok) throw new Error("Failed to mark notification read");
    return res.json();
  },
};

export const workspaceApi = {
  async listByOrg(orgId: string, page = 1, pageSize = 25): Promise<Paginated<Workspace>> {
    const res = await apiFetch(`/workspaces/?organization_id=${orgId}&page=${page}&page_size=${pageSize}`);
    if (!res.ok) throw new Error("Failed to list workspaces");
    return res.json();
  },
  async list(orgId: string, page = 1, pageSize = 25): Promise<Paginated<Workspace>> {
    return this.listByOrg(orgId, page, pageSize);
  },
  async create(data: { name: string; description?: string; organization_id: string }): Promise<Workspace> {
    const res = await apiFetch("/workspaces/", { method: "POST", body: JSON.stringify(data) });
    if (!res.ok) throw new Error(await extractErrorDetail(res, "Failed to create workspace"));
    return res.json();
  },
  async getById(id: string): Promise<Workspace> {
    const res = await apiFetch(`/workspaces/${id}`);
    if (!res.ok) throw new Error("Workspace not found");
    return res.json();
  },
};

export const documentApi = {
  async listByWorkspace(workspaceId: string, page = 1, pageSize = 25): Promise<Paginated<DocumentRecord>> {
    const res = await apiFetch(`/documents/?workspace_id=${workspaceId}&page=${page}&page_size=${pageSize}`);
    if (!res.ok) throw new Error("Failed to list documents");
    return res.json();
  },
  async list(workspaceId: string, page = 1, pageSize = 25): Promise<Paginated<DocumentRecord>> {
    return this.listByWorkspace(workspaceId, page, pageSize);
  },
  async upload(workspaceId: string, file: File): Promise<DocumentRecord> {
    const formData = new FormData();
    formData.append("workspace_id", workspaceId);
    formData.append("file", file);
    const res = await apiFetch("/documents/upload", { method: "POST", body: formData });
    if (!res.ok) throw new Error(await extractErrorDetail(res, "Failed to upload document"));
    return res.json();
  },
};

export const workflowApi = {
  async listTemplates(): Promise<WorkflowTemplate[]> {
    const res = await apiFetch("/workflows/templates");
    if (!res.ok) throw new Error("Failed to list workflow templates");
    return res.json();
  },
  async list(workspaceId: string, page = 1, pageSize = 25): Promise<Paginated<Workflow>> {
    const res = await apiFetch(`/workflows/?workspace_id=${workspaceId}&page=${page}&page_size=${pageSize}`);
    if (!res.ok) throw new Error("Failed to list workflows");
    return res.json();
  },
  async get(id: string): Promise<Workflow> {
    const res = await apiFetch(`/workflows/${id}`);
    if (!res.ok) throw new Error("Workflow not found");
    return res.json();
  },
  async create(data: {
    name: string;
    description?: string;
    template_id: string;
    workspace_id: string;
  }): Promise<Workflow> {
    const res = await apiFetch("/workflows/", { method: "POST", body: JSON.stringify(data) });
    if (!res.ok) throw new Error(await extractErrorDetail(res, "Failed to create workflow"));
    return res.json();
  },
  async run(workflowId: string, query?: string): Promise<WorkflowRun> {
    const res = await apiFetch(`/workflows/${workflowId}/run`, {
      method: "POST",
      body: JSON.stringify(query ? { query } : {}),
    });
    if (!res.ok) throw new Error(await extractErrorDetail(res, "Failed to start workflow run"));
    return res.json();
  },
  async listRuns(workflowId: string, page = 1, pageSize = 25): Promise<Paginated<WorkflowRun>> {
    const res = await apiFetch(`/workflows/${workflowId}/runs?page=${page}&page_size=${pageSize}`);
    if (!res.ok) throw new Error("Failed to list workflow runs");
    return res.json();
  },
  async approveRun(workflowId: string, runId: string, reason?: string): Promise<WorkflowRun> {
    const res = await apiFetch(`/workflows/${workflowId}/runs/${runId}/approve`, {
      method: "POST",
      body: JSON.stringify(reason ? { reason } : {}),
    });
    if (!res.ok) throw new Error(await extractErrorDetail(res, "Failed to approve workflow run"));
    return res.json();
  },
  async rejectRun(workflowId: string, runId: string, reason?: string): Promise<WorkflowRun> {
    const res = await apiFetch(`/workflows/${workflowId}/runs/${runId}/reject`, {
      method: "POST",
      body: JSON.stringify(reason ? { reason } : {}),
    });
    if (!res.ok) throw new Error(await extractErrorDetail(res, "Failed to reject workflow run"));
    return res.json();
  },
};

export const analyticsApi = {
  async overview(): Promise<AnalyticsOverview> {
    const res = await apiFetch("/analytics/overview");
    if (!res.ok) throw new Error("Failed to load analytics");
    return res.json();
  },
  async documents(page = 1, pageSize = 25): Promise<Paginated<DocumentRecord & { workspace: string }>> {
    const res = await apiFetch(`/analytics/documents?page=${page}&page_size=${pageSize}`);
    if (!res.ok) throw new Error("Failed to load document analytics");
    return res.json();
  },
  async modelPerformance(days = 7, page = 1, pageSize = 10): Promise<ModelPerformanceResponse> {
    const res = await apiFetch(
      `/analytics/model-performance?days=${days}&page=${page}&page_size=${pageSize}`
    );
    if (!res.ok) throw new Error("Failed to load AI model performance");
    return res.json();
  },
};

export const connectorApi = {
  async list(workspaceId: string, page = 1, pageSize = 25): Promise<Paginated<Connector>> {
    const res = await apiFetch(`/connectors/?workspace_id=${workspaceId}&page=${page}&page_size=${pageSize}`);
    if (!res.ok) throw new Error("Failed to list connectors");
    return res.json();
  },
  async connect(data: {
    provider: string;
    workspace_id: string;
    name: string;
    access_token: string;
    config: Record<string, string>;
  }): Promise<Connector> {
    const res = await apiFetch("/connectors/", { method: "POST", body: JSON.stringify(data) });
    if (!res.ok) throw new Error(await extractErrorDetail(res, "Failed to connect integration"));
    return res.json();
  },
  /** Start an OAuth2 connector install (Slack, Google Drive): fetch the
   * provider's consent-screen URL (authenticated) and navigate there. */
  async connectOAuth(provider: string, workspaceId: string): Promise<void> {
    const res = await apiFetch(
      `/connectors/oauth/${provider}/authorize?workspace_id=${workspaceId}`
    );
    if (!res.ok) throw new Error(await extractErrorDetail(res, "Failed to start OAuth connection"));
    const { authorize_url } = await res.json();
    window.location.href = authorize_url;
  },
  async disconnect(id: string): Promise<Connector> {
    const res = await apiFetch(`/connectors/${id}/disconnect`, { method: "POST" });
    if (!res.ok) throw new Error(await extractErrorDetail(res, "Failed to disconnect integration"));
    return res.json();
  },
  async sync(id: string): Promise<{ id: string; status: string; detail: string }> {
    const res = await apiFetch(`/connectors/${id}/sync`, { method: "POST" });
    if (!res.ok) throw new Error(await extractErrorDetail(res, "Failed to trigger sync"));
    return res.json();
  },
  async health(id: string): Promise<ConnectorHealth> {
    const res = await apiFetch(`/connectors/${id}/health`);
    if (!res.ok) throw new Error("Failed to check connector health");
    return res.json();
  },
};
