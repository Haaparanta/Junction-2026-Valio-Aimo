/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const gateway = process.env.GATEWAY_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // The buyer UI talks to the local gateway; ElevenLabs reaches the gateway through ngrok.
    proxy: { "/api": gateway, "/v1": gateway, "/health": gateway },
  },
  test: { environment: "jsdom", include: ["src/**/*.test.ts"] },
});
