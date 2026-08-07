import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { isAccessTokenValid } from "@/lib/jwt";

const publicPaths = ["/", "/login", "/register"];

const protectedPrefixes = [
  "/dashboard",
  "/chat",
  "/documents",
  "/workflows",
  "/analytics",
  "/settings",
];

function redirectToLogin(request: NextRequest) {
  const loginUrl = new URL("/login", request.url);
  loginUrl.searchParams.set("redirect", request.nextUrl.pathname + request.nextUrl.search);
  return NextResponse.redirect(loginUrl);
}

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (publicPaths.includes(pathname)) {
    return NextResponse.next();
  }

  const isProtected = protectedPrefixes.some(
    (prefix) => pathname === prefix || pathname.startsWith(prefix + "/")
  );

  if (!isProtected) {
    return NextResponse.next();
  }

  const token =
    request.cookies.get("access_token")?.value ||
    request.headers.get("authorization")?.replace("Bearer ", "");

  if (!token) {
    return redirectToLogin(request);
  }

  // Verify the JWT signature + expiry before treating the request as
  // authenticated. A cookie containing an arbitrary value no longer passes.
  // (Edge runtime: WebCrypto HS256 check; the API still fully re-verifies the
  // token server-side on every protected call.)
  const secret = process.env.JWT_SECRET_KEY;
  if (!secret || !(await isAccessTokenValid(token, secret))) {
    return redirectToLogin(request);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/chat/:path*",
    "/documents/:path*",
    "/workflows/:path*",
    "/analytics/:path*",
    "/settings/:path*",
  ],
};
