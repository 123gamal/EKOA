/** Unique test-data generators so repeated E2E runs never collide on unique DB constraints. */

export function uniqueSuffix(): string {
  return crypto.randomUUID().replace(/-/g, "").slice(0, 12);
}

export function uniqueEmail(prefix = "e2e"): string {
  // NOT ekoa.test / any .test domain — the backend's real email-validator
  // rejects reserved special-use TLDs (test/example/invalid/localhost) as a
  // syntax error (422), regardless of deliverability checking. example.com
  // is the same domain tests/performance/locustfile.py already uses.
  return `${prefix}-${uniqueSuffix()}@example.com`;
}

export function uniqueOrgName(): string {
  return `E2E Org ${uniqueSuffix()}`;
}

export function uniqueWorkspaceName(): string {
  return `E2E Workspace ${uniqueSuffix()}`;
}

export const E2E_PASSWORD = "E2ePassw0rd!";
