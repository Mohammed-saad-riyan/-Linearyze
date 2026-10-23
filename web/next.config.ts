import type { NextConfig } from "next";

// The browser only ever talks to this origin, so the session cookie stays first-party and
// no CORS is needed. On Vercel, /api is routed to the FastAPI service by vercel.json before
// it reaches Next.js; this rewrite only matters for local `next dev` and docker compose.
const apiOrigin = process.env.API_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: process.env.VERCEL ? undefined : "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  experimental: {
    // An answer that is drafted, validated and regenerated once can take ~20 s.
    proxyTimeout: 90_000,
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  },
};

export default nextConfig;
