import { expect, test } from '@playwright/test'

import { ADMIN, login } from './helpers'

test.describe('鉴权', () => {
  test('未登录访问受保护页面会被重定向到登录页', async ({ page }) => {
    await page.goto('/datasources')
    await page.waitForURL(/\/login/, { timeout: 30_000 })
    await expect(page.locator('button.login-submit')).toBeVisible()
  })

  test('口令错误时给出可读的行内错误，且不会跳转', async ({ page }) => {
    await page.goto('/login')
    await page.locator('input[placeholder="admin"]').fill(ADMIN.username)
    await page.locator('input[placeholder="请输入密码"]').fill('definitely-wrong-password')
    await page.locator('button.login-submit').click()

    await expect(page.getByText(/用户名或密码错误/)).toBeVisible({ timeout: 30_000 })
    await expect(page).toHaveURL(/\/login/)
  })

  test('登录成功后进入对话页并带上身份', async ({ page }) => {
    await login(page)
    // 侧边栏账号块：title 是登录名，正文是显示名 + 角色 + 权限数
    const chip = page.locator('.user-chip')
    await expect(chip).toBeVisible()
    await expect(chip).toHaveAttribute('title', ADMIN.username)
    await expect(page.locator('.user-name')).not.toBeEmpty()
    await expect(page.locator('.user-role')).toBeVisible()
    await expect(page.getByText(/\d+ 项权限/)).toBeVisible()
    await expect(page.getByRole('link', { name: /对话/ }).first()).toBeVisible()
  })
})
