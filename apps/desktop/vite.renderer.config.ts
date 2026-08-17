import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "./",
  root: ".",
  build: {
    outDir: ".vite/renderer/main_window",
    emptyOutDir: true,
    sourcemap: true,
  },
  server: {
    port: 5185,
  },
});
