import { defineConfig } from "vite";
import { resolve } from "node:path";

// Pages: landing, the map for one rule, organization scorecards, methods, connect (MCP), prepare, admin.
export default defineConfig({
  server: { port: 5177, proxy: { "/api": "http://127.0.0.1:8077" } },
  build: {
    outDir: "dist", emptyOutDir: true, chunkSizeWarningLimit: 900,
    rollupOptions: { input: Object.fromEntries(["index", "rule", "org", "methods", "connect", "prepare", "admin"].map((n) => [n, resolve(import.meta.dirname, `${n}.html`)])) },
  },
});
