import { defineConfig } from '@playwright/test';

// Real Google Chrome (channel 'chrome'), headed, with a throw-away profile (never the personal profile).
export default defineConfig({
  testDir: './tests/e2e',
  globalSetup: './tests/e2e/global-setup.ts',
  timeout: 60_000,
  workers: 1,
  reporter: [['list'], ['json', { outputFile: 'qa-artifacts/playwright-report.json' }]],
  outputDir: 'qa-artifacts/test-results',
  use: {
    baseURL: process.env.XAU_BASE_URL ?? 'http://127.0.0.1:8765',
    channel: 'chrome',
    storageState: 'qa-artifacts/auth-state.json',
    headless: process.env.XAU_HEADLESS === '1',
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
});
