import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const API_URL = process.env.API_URL || "http://localhost:8000";
const AI_URL = process.env.AI_URL || "http://localhost:8001";

const nextConfig: NextConfig = {
  // Let /api/v1/* paths with a trailing slash reach the rewrite directly
  // instead of being 308-redirected (FastAPI then 307-redirects back, which
  // would loop the browser).
  skipTrailingSlashRedirect: true,
  async rewrites() {
    return [
      // Match trailing-slash paths first: Next's `:path*` capture strips the
      // trailing slash, so a rewrite ending in `/:path*` would forward
      // `/api/v1/organizations/` as `/api/v1/organizations` and FastAPI would
      // 307-redirect to an internal host the browser cannot reach.
      {
        source: "/api/v1/ai/:path*/",
        destination: `${AI_URL}/api/v1/ai/:path*/`,
      },
      {
        source: "/api/v1/:path*/",
        destination: `${API_URL}/api/v1/:path*/`,
      },
      {
        source: "/api/v1/ai/:path*",
        destination: `${AI_URL}/api/v1/ai/:path*`,
      },
      {
        source: "/api/v1/:path*",
        destination: `${API_URL}/api/v1/:path*`,
      },
    ];
  },
};

export default withNextIntl(nextConfig);
