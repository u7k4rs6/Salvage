import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// The dev server is loopback only and proxies /api to the FastAPI process, so the browser sees
// one origin and the API stays bound to 127.0.0.1 (docs/03_SECURITY_AND_ACCESS.md section 9).
// A static host serves files, so a deep link like /runner has to be rewritten to index.html by the
// host. vercel.json does it on Vercel; GitHub Pages has no rewrite rule, so the build copies
// index.html to 404.html and Pages serves that for any unknown path, which is the same thing by a
// different route.
//
// `VITE_BASE` is for a Pages deployment under a repository subpath. It defaults to root, which is
// what Vercel and a user-or-organisation Pages site want.
export default defineConfig(({ mode }) => ({
  base: loadEnv(mode, ".", "VITE_").VITE_BASE ?? "/",
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: false,
        // Server-sent events need the proxy to stream rather than buffer.
        ws: false,
      },
    },
  },
  preview: { host: "127.0.0.1", port: 4173, strictPort: true },
  build: {
    outDir: "dist",
    sourcemap: false,
    rollupOptions: {
      output: {
        // Recharts is a third of the bundle and only Results draws a chart, so it is split out and
        // the visitor who never opens Results never downloads it.
        manualChunks: (id) =>
          id.includes("node_modules/recharts") || id.includes("node_modules/d3-")
            ? "charts"
            : undefined,
      },
    },
  },
}));
