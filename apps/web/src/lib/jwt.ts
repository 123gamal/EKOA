/**
 * Lightweight HS256 JWT verification for Next.js middleware (edge runtime).
 *
 * Uses WebCrypto (`crypto.subtle`) so no Node-specific or extra dependency is
 * needed. This performs a real signature + expiry check — it does NOT trust
 * the token just because a cookie is present. Full verification still happens
 * server-side on every API call via the API's `get_current_user` dependency.
 */

function base64UrlToBytes(value: string): Uint8Array {
  let b64 = value.replace(/-/g, "+").replace(/_/g, "/");
  while (b64.length % 4) b64 += "=";
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

function decodePayload(token: string): Record<string, unknown> | null {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const payload = JSON.parse(new TextDecoder().decode(base64UrlToBytes(parts[1])));
    return typeof payload === "object" && payload !== null ? (payload as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

export function isTokenExpired(token: string): boolean {
  const payload = decodePayload(token);
  if (!payload || typeof payload.exp !== "number") return true;
  return Date.now() >= payload.exp * 1000;
}

export async function verifyTokenSignature(token: string, secret: string): Promise<boolean> {
  const parts = token.split(".");
  if (parts.length !== 3 || !secret) return false;
  try {
    const key = await crypto.subtle.importKey(
      "raw",
      new TextEncoder().encode(secret),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["verify"],
    );
    const data = new TextEncoder().encode(`${parts[0]}.${parts[1]}`);
    return await crypto.subtle.verify("HMAC", key, base64UrlToBytes(parts[2]), data);
  } catch {
    return false;
  }
}

export async function isAccessTokenValid(token: string, secret: string): Promise<boolean> {
  if (!token || !secret) return false;
  const signatureOk = await verifyTokenSignature(token, secret);
  if (!signatureOk) return false;
  return !isTokenExpired(token);
}
