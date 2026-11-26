import { writeFileSync } from 'node:fs'

import { expect, test } from '@playwright/test'

import { ask, lastAnswer, login, newChat } from './helpers'

// 这几步有前后依赖（先问出对话，才谈得上出报告），串行执行
test.describe.configure({ mode: 'serial' })

test.beforeEach(async ({ page }) => {
  await login(page)
})

test('具体问题：出 SQL + 图表 + 结果表', async ({ page }) => {
  await newChat(page)
  await ask(page, '2026年各城市的销售额排名')

  const answer = lastAnswer(page)
  await expect(answer.getByText('生成的 SQL')).toBeVisible()
  await expect(answer.locator('.sql-code').first()).toContainText(/SELECT/i)
  // 图表是 ECharts 渲染的 canvas，没有语义节点，只能断言元素存在
  await expect(answer.locator('canvas').first()).toBeVisible({ timeout: 60_000 })
  // 注意：图表标题也叫「查询结果 (N 行)」，这里必须精确定位结果表卡片
  await expect(answer.locator('.result-table .card-title')).toHaveText('查询结果')
  await expect(answer.locator('table.data-table tbody tr')).not.toHaveCount(0)
})

test('模糊问题：不猜，给出澄清选项', async ({ page }) => {
  await newChat(page)
  await ask(page, '帮我看看销售情况')

  const answer = lastAnswer(page)
  await expect(answer.getByText(/请问您?想?(看|了解)|请选择要继续的方向/)).toBeVisible()

  const options = answer.locator('.option-btn')
  await expect(options.first()).toBeVisible()
  expect(await options.count()).toBeGreaterThan(0)

  // 点一个选项能直接续问（说明选项不是装饰）：这一轮同样会走完 +2 条消息
  const before = await page.locator('.message').count()
  await options.first().click()
  await expect(page.locator('.message')).toHaveCount(before + 2, { timeout: 180_000 })
  await expect(
    lastAnswer(page).locator('canvas, .result-table').first(),
  ).toBeVisible({ timeout: 60_000 })
})

test('上传脏 CSV：给出清洗报告', async ({ page }, testInfo) => {
  // 自带样本，避免依赖 seed 生成的文件路径（Windows / Linux 差异）
  const csvPath = testInfo.outputPath('e2e-messy.csv')
  writeFileSync(
    csvPath,
    ' 门店编号 ,城市,销售额\n0012, 杭州 ,100\n0012, 杭州 ,100\n,,\n',
    'utf8',
  )

  await page.goto('/datasources')
  await page.getByRole('button', { name: /上传文件/ }).click()
  await page.locator('input[type="file"]').setInputFiles(csvPath)
  // 弹窗是两步式：选完文件再点「开始上传」
  await page.getByRole('button', { name: /开始上传/ }).click()

  await expect(page.getByText(/上传成功，已建为数据源/)).toBeVisible({ timeout: 90_000 })
  const pageText = await page.locator('body').innerText()
  expect(pageText).toMatch(/丢弃 1 行全空记录/)
  expect(pageText).toMatch(/丢弃 1 行完全重复记录/)
  expect(pageText).toMatch(/前导零/)

  // 关掉弹窗后，列表里能看到新数据源
  await page.keyboard.press('Escape')
  await expect(page.getByText('e2e-messy.csv').first()).toBeVisible()
})

test('生成报告并下载 Markdown', async ({ page }) => {
  await page.goto('/reports')
  const select = page.locator('select').first()
  await expect(select).toBeVisible()
  // 列表按时间倒序，第一条就是上一轮对话
  await expect(select.locator('option')).not.toHaveCount(1)
  await select.selectOption({ index: 1 })

  await page.getByRole('button', { name: /生成报告/ }).click()
  await expect(page.locator('.report-item').first()).toBeVisible({ timeout: 90_000 })

  await page.locator('.report-item').first().getByRole('button', { name: /预览/ }).click()
  await expect(page.getByText(/数据分析报告/).first()).toBeVisible({ timeout: 30_000 })

  // 下载按钮走 blob + a[download]，Playwright 能收到 download 事件
  const [download] = await Promise.all([
    page.waitForEvent('download', { timeout: 60_000 }),
    page.locator('.report-item').first().getByRole('button', { name: 'MD', exact: true }).click(),
  ])
  expect(download.suggestedFilename()).toMatch(/\.md$/i)
})
