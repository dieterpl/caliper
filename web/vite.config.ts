import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

// The Python app (web/server.py) is the real backend in every mode: it proxies
// the butai daemon, relays /ws, serves artifacts under /w and does token auth.
// In `npm run dev` Vite serves the SPA and forwards those paths to it.
const BACKEND = process.env.CALIPER_SERVER || "http://localhost:8017";

const proxy = {
  "/api": BACKEND,
  "/butai": BACKEND,
  "/w": BACKEND,
  "/login": BACKEND,
  "/ws": { target: BACKEND, ws: true },
} as const;

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      // Keep the proven, wasm-inline Rapier build the physics code was written
      // against, instead of pulling a possibly API-incompatible one from npm.
      "@dimforge/rapier3d-compat": fileURLToPath(
        new URL("./vendor/rapier.es.js", import.meta.url),
      ),
    },
  },
  server: { proxy },
  preview: { proxy },
  build: { outDir: "dist", emptyOutDir: true },
});
