import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests/browser', fullyParallel: false, workers: 1, retries: 0,
  reporter: 'list', timeout: 45000,
  use: { baseURL: 'http://127.0.0.1:4310', browserName: 'chromium', trace: 'off', video: 'off' },
  webServer: { command: 'npm run preview', url: 'http://127.0.0.1:4310', reuseExistingServer: false }
});
