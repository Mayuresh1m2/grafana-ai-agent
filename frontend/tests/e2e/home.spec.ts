import { expect, test } from '@playwright/test'

test.describe('Home page', () => {
  test('smoke: page loads and shows title', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('h1')).toContainText('Grafana AI Agent')
  })

  test('page has Start chatting link', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('link', { name: /start chatting/i })).toBeVisible()
  })

  test('clicking Start chatting navigates to /chat', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('link', { name: /start chatting/i }).click()
    await expect(page).toHaveURL('/chat')
  })

  test('nav link to Chat works', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('navigation').getByRole('link', { name: 'Chat' }).click()
    await expect(page).toHaveURL('/chat')
  })
})

test.describe('Chat page', () => {
  test('smoke: chat page loads', async ({ page }) => {
    await page.goto('/chat')
    await expect(page.locator('.query-input')).toBeVisible()
  })

  test('shows empty state on fresh load', async ({ page }) => {
    await page.goto('/chat')
    await expect(page.locator('.empty-state')).toBeVisible()
  })
})

test.describe('404 page', () => {
  test('unknown route shows 404 message', async ({ page }) => {
    await page.goto('/this-does-not-exist')
    await expect(page.locator('.code')).toContainText('404')
  })
})
