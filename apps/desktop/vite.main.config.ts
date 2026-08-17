import { defineConfig } from "vite";

const external = [
  "electron",
  "extract-zip",
  "http-proxy",
  "child_process",
  "events",
  "fs",
  "fs/promises",
  "http",
  "net",
  "os",
  "path",
  "stream",
  "url",
  "util",
  "zlib",
  "node:child_process",
  "node:events",
  "node:fs",
  "node:fs/promises",
  "node:http",
  "node:net",
  "node:os",
  "node:path",
  "node:stream",
  "node:url",
  "node:util",
  "node:zlib",
];

export default defineConfig({
  build: {
    target: "node20",
    outDir: ".vite/build",
    emptyOutDir: false,
    sourcemap: true,
    lib: {
      entry: "src/main/index.ts",
      formats: ["es"],
      fileName: () => "main.js",
    },
    rollupOptions: {
      external,
    },
  },
});
