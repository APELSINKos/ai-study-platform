import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  poweredByHeader: false,
  // Do not let the dev server write agent instruction files into the repo.
  agentRules: false,
};

export default withNextIntl(nextConfig);
