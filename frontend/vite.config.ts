import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    watch: {
      // Poll for file changes — required for hot-reload to work
      // reliably across Docker volume mounts on Windows/Mac
      usePolling: true,
      interval: 500,
    },
    proxy: {
      // Forward /api/* requests to the backend container
      // This avoids CORS issues during development
      "/api": {
        target: "http://backend:8000",
        changeOrigin: true,
      },
    },
  },
});