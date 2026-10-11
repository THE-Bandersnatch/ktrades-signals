import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // In production Vercel routes /api/* to the Flask service (vercel.json).
  // Locally, run the backend with `flask --app backend/app run -p 5328`
  // and `next dev` forwards /api calls to it.
  async rewrites() {
    if (process.env.NODE_ENV !== "development") return [];
    return [{ source: "/api/:path*", destination: "http://127.0.0.1:5328/api/:path*" }];
  },
};

export default nextConfig;
