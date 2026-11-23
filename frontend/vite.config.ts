import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// El backend local escucha en 127.0.0.1:8765. En desarrollo, Vite hace de proxy de /api
// (HTTP y WebSocket): el navegador ve un único origen, así la cookie del refresh token
// (SameSite=Strict, Path=/api/v1/auth) funciona sin CORS.
const BACKEND = process.env.MILT_BACKEND_URL ?? "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true, ws: true },
    },
  },
  build: {
    target: "es2022",
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    restoreMocks: true,
    // Equipos con poca RAM: hilos en lugar de procesos y como mucho 2 a la vez.
    pool: "threads",
    maxWorkers: 2,
  },
});
