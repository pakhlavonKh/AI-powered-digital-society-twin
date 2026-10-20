import type { NextConfig } from "next";

// Server-side only (no NEXT_PUBLIC_ prefix): the browser talks to /api/v1 and /api/v2 on this origin and
// Next forwards it, so no backend address or environment value reaches the client bundle.
const apiOrigin = process.env.SOCIETYTWIN_API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  async rewrites() {
    return [
      { source: "/api/v1/:path*", destination: `${apiOrigin}/api/v1/:path*` },
      { source: "/api/v2/:path*", destination: `${apiOrigin}/api/v2/:path*` },
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
    ];
  },
};

export default nextConfig;
