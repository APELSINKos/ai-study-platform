import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

// The browser only talks to Next.js; API calls are proxied so auth cookies stay first-party.
const BACKEND_URL = process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  // Compose publishes the web client on 127.0.0.1, and Docker Desktop links it by that address;
  // the dev server serves its client scripts only to localhost and the origins listed here.
  allowedDevOrigins: ["127.0.0.1"],
  experimental: {
    // The /api proxy cuts bodies beyond this; it must pass a 20 MiB upload plus multipart overhead.
    proxyClientMaxBodySize: "21mb",
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` }];
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default withNextIntl(nextConfig);
