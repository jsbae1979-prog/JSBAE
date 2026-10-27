import { defineConfig } from "vite";
export default defineConfig({
  base: "/studio/",
  build: { outDir: "dist", emptyOutDir: true },
  server: { host: "127.0.0.1", port: 18766, strictPort: true },
});
