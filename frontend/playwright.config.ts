import { defineConfig, devices } from '@playwright/test'

/**
 * 端到端冒烟配置。
 *
 * 为什么单独一套：后端 pytest 覆盖不到"浏览器里点一遍"这件事（路由守卫、SSE 渲染、
 * 图表 canvas、上传弹窗、报告下载），而这几条恰好是最容易在改前端时静默坏掉的路径。
 *
 * 本地（Windows）用系统 Edge，避免下载 chromium：
 *   set PW_CHANNEL=msedge && set PLAYWRIGHT_BASE_URL=http://127.0.0.1:5199
 *   set PW_NO_WEB_SERVER=1   # 自己起 dev server，可指到不同 api 端口
 * CI 里用 `npx playwright install chromium` 装浏览器，webServer 自动拉起 vite。
 */
const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173'
const startOwnServer = !process.env.PW_NO_WEB_SERVER

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 180_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL,
    channel: (process.env.PW_CHANNEL as 'msedge' | 'chrome' | undefined) || undefined,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    actionTimeout: 30_000,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: startOwnServer
    ? {
        // 必须显式 --host 127.0.0.1：Linux runner 上 `localhost` 可能先解析到 ::1，
        // 而健康检查打的是 127.0.0.1，会导致 "Timed out waiting from config.webServer"。
        command: 'npm run dev -- --host 127.0.0.1 --port 5173 --strictPort',
        url: 'http://127.0.0.1:5173',
        reuseExistingServer: !process.env.CI,
        timeout: 180_000,
      }
    : undefined,
})
