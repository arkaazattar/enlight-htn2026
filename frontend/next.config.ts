import type { NextConfig } from "next";
import { loadEnvConfig } from "@next/env";
import path from "node:path";

const frontendDir = __dirname;
const rootEnv = loadEnvConfig(path.resolve(frontendDir, ".."), undefined, undefined, true);
loadEnvConfig(frontendDir, undefined, undefined, true);

const nextConfig: NextConfig = {
  env: {
    NEXT_PUBLIC_GOOGLE_MAPS_API_KEY: rootEnv.parsedEnv?.GOOGLE_MAPS_API_KEY ?? rootEnv.combinedEnv.GOOGLE_MAPS_API_KEY ?? "",
    NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID: rootEnv.parsedEnv?.GOOGLE_MAPS_MAP_ID ?? rootEnv.combinedEnv.GOOGLE_MAPS_MAP_ID ?? "",
  },
};

export default nextConfig;
