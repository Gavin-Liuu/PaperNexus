import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  use: { baseURL: 'http://127.0.0.1:5178', viewport: { width: 1500, height: 1000 }, channel: 'msedge', headless: true },
  webServer: { command: 'npm run dev -- --host 127.0.0.1 --port 5178', url: 'http://127.0.0.1:5178', reuseExistingServer: false },
})
