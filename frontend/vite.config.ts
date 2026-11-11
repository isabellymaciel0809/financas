/// <reference types="node" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // O teste end-to-end aponta para uma API própria, com banco temporário (playwright.config.ts).
      "/api": process.env.API_URL ?? "http://localhost:8000",
    },
  },
});
