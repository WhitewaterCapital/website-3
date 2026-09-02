import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The engine exports live in public/data and are read at runtime with
  // fs.readFile. On Vercel, public/ assets are NOT in the serverless function
  // filesystem by default, so force-include the JSON in the traced bundle for
  // the routes that read them (Sentimentum · Macro/Equity, and the stress flow).
  outputFileTracingIncludes: {
    "/sentiment": [
      "./public/data/aurora/latest.json",
      "./public/data/incepta/latest.json",
    ],
    "/intra-exitus": ["./public/data/intra-exitus/latest.json"],
    "/api/models/stress": ["./public/data/incepta/latest.json"],
  },
};

export default nextConfig;
