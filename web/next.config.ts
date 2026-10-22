import type { NextConfig } from "next";

// The browser only ever talks to this origin; /api is proxied to FastAPI so the session
// cookie stays first-party and no CORS is needed.
const apiOrigin = process.env.API_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
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
