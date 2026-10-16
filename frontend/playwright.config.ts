import { defineConfig, devices } from "@playwright/test";

// The browser flow runs against the artificial test fixture, never the real Ankara data or a provider.
// scripts/e2e.sh starts both servers with a throwaway state directory.
const port = Number(process.env.E2E_WEB_PORT ?? 3100);

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "off",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", testMatch: /workbench\.spec\.ts/, use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 900 } } },
    { name: "narrow", testMatch: /narrow\.spec\.ts/, use: { ...devices["Pixel 7"] } },
  ],
});
