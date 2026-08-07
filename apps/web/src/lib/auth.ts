const ACCESS_KEY = "access_token";
const ACCESS_MAX_AGE = 60 * 60 * 24;

// NOTE: The refresh token is intentionally NOT stored here. It is delivered by
// the API in an HttpOnly (Secure in production, SameSite=Lax) cookie, so it is
// never readable by client-side JS. The client only keeps the short-lived
// access token, which is refreshed automatically on 401 (see lib/api.ts).

export function setTokens(accessToken: string) {
  if (typeof window === "undefined") return;
  localStorage.setItem(ACCESS_KEY, accessToken);
  // Non-httpOnly cookie so Next.js middleware can read the access token for
  // page-gating (it verifies signature + expiry, not just presence).
  document.cookie = `${ACCESS_KEY}=${accessToken}; path=/; max-age=${ACCESS_MAX_AGE}; SameSite=Lax`;
}

export function clearTokens() {
  if (typeof window === "undefined") return;
  localStorage.removeItem(ACCESS_KEY);
  document.cookie = `${ACCESS_KEY}=; path=/; max-age=0`;
  // The refresh-token cookie is HttpOnly and is cleared by the API on
  // /auth/logout; it cannot (and should not) be cleared from JS.
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(ACCESS_KEY);
}

export function isAuthenticated(): boolean {
  return !!getAccessToken();
}
