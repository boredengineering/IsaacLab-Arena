import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
  testDir: './tests/e2e',
  timeout: 75_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  webServer:
    process.env.WORKBENCH_E2E_STATIC === '1'
      ? {
          command: 'npm exec vite -- preview --host 127.0.0.1 --port 4173 --strictPort',
          url: 'http://127.0.0.1:4173',
          reuseExistingServer: false,
        }
      : undefined,
  use: {
    baseURL: process.env.WORKBENCH_BASE_URL ?? 'http://127.0.0.1:3000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1050 } },
    },
  ],
});
