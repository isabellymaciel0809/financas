import { existsSync } from "node:fs";
import { defineConfig, devices } from "@playwright/test";

// Portas próprias, para não colidir com o app de desenvolvimento (8000 e 5173).
const API_PORT = 8010;
const WEB_PORT = 5180;

// Python do ambiente virtual do backend, se existir (desenvolvimento); senão, o do sistema (CI).
const venvPython = process.platform === "win32" ? "../backend/.venv/Scripts/python.exe" : "../backend/.venv/bin/python";
const python = process.env.E2E_PYTHON ?? (existsSync(venvPython) ? venvPython : "python");

export default defineConfig({
  testDir: "e2e",
  fullyParallel: false, // os testes compartilham o mesmo banco (o primeiro cria a conta)
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    locale: "pt-BR",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      // Banco novo e temporário a cada execução (veja backend/scripts/e2e_server.py).
      command: `"${python}" ../backend/scripts/e2e_server.py ${API_PORT}`,
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npx vite --port ${WEB_PORT} --strictPort`,
      url: `http://localhost:${WEB_PORT}`,
      env: { API_URL: `http://127.0.0.1:${API_PORT}` },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
