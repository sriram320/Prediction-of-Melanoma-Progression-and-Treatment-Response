import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: the SPA runs on :5173 and proxies /api to the FastAPI backend on :8000, so the browser
// sees one origin and the SameSite=Strict refresh cookie works exactly as in production.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: false },
    },
  },
  build: { sourcemap: false },
});
