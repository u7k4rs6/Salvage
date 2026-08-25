import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server is loopback only and proxies /api to the FastAPI process, so the browser sees
// one origin and the API stays bound to 127.0.0.1 (docs/03_SECURITY_AND_ACCESS.md section 9).
export default defineConfig({
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
  build: { outDir: "dist", sourcemap: false },
});
