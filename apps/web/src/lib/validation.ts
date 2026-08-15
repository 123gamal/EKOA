import { z } from "zod";

export const loginSchema = z.object({
  email: z.string().trim().min(1, "Email is required").email("Enter a valid email address"),
  password: z.string().min(1, "Password is required"),
});

export const registerSchema = z.object({
  fullName: z.string().trim().min(1, "Full name is required").max(120, "Full name is too long"),
  email: z.string().trim().min(1, "Email is required").email("Enter a valid email address"),
  password: z
    .string()
    .min(8, "Password must be at least 8 characters")
    .max(128, "Password is too long"),
});

export const createWorkflowSchema = z.object({
  name: z.string().trim().min(1, "Workflow name is required").max(120, "Workflow name is too long"),
  description: z.string().trim().max(500, "Description is too long").optional(),
  query: z.string().trim().max(2000, "Query is too long").optional(),
});

export const approvalDecisionSchema = z.object({
  reason: z.string().trim().max(500, "Reason is too long").optional(),
});

export const connectConnectorSchema = z.object({
  workspaceId: z.string().min(1, "Select a workspace"),
  name: z
    .string()
    .trim()
    .min(1, "Integration name is required")
    .max(255, "Integration name is too long"),
  owner: z.string().trim().min(1, "Repository owner is required").max(255),
  repo: z.string().trim().min(1, "Repository name is required").max(255),
  accessToken: z
    .string()
    .min(1, "Personal access token is required")
    .max(512, "Token is too long"),
});

export const connectJiraSchema = z.object({
  workspaceId: z.string().min(1, "Select a workspace"),
  name: z.string().trim().min(1, "Integration name is required").max(255),
  baseUrl: z.string().trim().min(1, "Base URL is required").max(255),
  projectKey: z.string().trim().min(1, "Project key is required").max(50),
  email: z.string().trim().min(1, "Email is required").email("Enter a valid email address"),
  apiToken: z.string().min(1, "API token is required").max(512),
});

export const connectNotionSchema = z.object({
  workspaceId: z.string().min(1, "Select a workspace"),
  name: z.string().trim().min(1, "Integration name is required").max(255),
  resourceId: z.string().trim().min(1, "Page or database ID is required").max(255),
  resourceType: z.enum(["page_id", "database_id"]),
  accessToken: z.string().min(1, "Integration token is required").max(512),
});

export const connectConfluenceSchema = z.object({
  workspaceId: z.string().min(1, "Select a workspace"),
  name: z.string().trim().min(1, "Integration name is required").max(255),
  baseUrl: z.string().trim().min(1, "Base URL is required").max(255),
  spaceKey: z.string().trim().min(1, "Space key is required").max(50),
  email: z.string().trim().min(1, "Email is required").email("Enter a valid email address"),
  apiToken: z.string().min(1, "API token is required").max(512),
});

export type LoginValues = z.infer<typeof loginSchema>;
export type RegisterValues = z.infer<typeof registerSchema>;
export type CreateWorkflowValues = z.infer<typeof createWorkflowSchema>;
export type ApprovalDecisionValues = z.infer<typeof approvalDecisionSchema>;
export type ConnectConnectorValues = z.infer<typeof connectConnectorSchema>;
export type ConnectJiraValues = z.infer<typeof connectJiraSchema>;
export type ConnectNotionValues = z.infer<typeof connectNotionSchema>;
export type ConnectConfluenceValues = z.infer<typeof connectConfluenceSchema>;
