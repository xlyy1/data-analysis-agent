import { expect, type Page } from '@playwright/test'

export const ADMIN = { username: 'admin', password: 'admin12345' }

/** 登录并等到对话页就绪 */
export async function login(page: Page, creds = ADMIN): Promise<void> {
  await page.goto('/login')
  await page.locator('input[placeholder="admin"]').fill(creds.username)
  await page.locator('input[placeholder="请输入密码"]').fill(creds.password)
  await page.locator('button.login-submit').click()
  await page.waitForURL((url) => new URL(url).pathname === '/', { timeout: 30_000 })
  await expect(page.locator('.chat-input')).toBeVisible()
}

/**
 * 开一个新会话。
 * 应用会恢复上次会话，如果不重置，断言会命中历史消息（这是本地首版失败的真实原因）。
 */
export async function newChat(page: Page): Promise<void> {
  await page.locator('.new-chat').click()
  await expect(page.locator('.message')).toHaveCount(0, { timeout: 30_000 })
}

/** 提问并等到这一轮真的回答完（消息数 +2 且输入框回到空闲态） */
export async function ask(page: Page, question: string): Promise<void> {
  const input = page.locator('.chat-input')
  const before = await page.locator('.message').count()
  await input.fill(question)
  await input.press('Enter')

  // 发送成功的第一个信号：输入框被清空
  await expect(input).toHaveValue('', { timeout: 30_000 })
  // 用户消息 + 助手消息都到位才算这一轮结束
  await expect(page.locator('.message')).toHaveCount(before + 2, { timeout: 180_000 })
  await expect(input).toHaveAttribute('placeholder', /向 DataAgent 提问/, { timeout: 30_000 })
}

/** 只看最后一条助手消息，避免命中历史 */
export function lastAnswer(page: Page) {
  return page.locator('.message.assistant').last()
}
