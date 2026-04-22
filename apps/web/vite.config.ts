import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        ws: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
        // SSE (EventSource) through dev proxy: avoid buffering / stale Content-Length
        configure(proxy) {
          proxy.on("proxyRes", (proxyRes, req) => {
            const url = req.url ?? "";
            if (url.includes("/events")) {
              delete proxyRes.headers["content-length"];
              proxyRes.headers["cache-control"] = "no-cache, no-transform";
              proxyRes.headers["x-accel-buffering"] = "no";
            }
          });
        },
      },
    },
  },
});
