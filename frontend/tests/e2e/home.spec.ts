import { expect, test } from '@playwright/test'

test.describe('Root redirect', () => {
  test('/ redirects to /setup when not configured', async ({ page }) => {
    await page.goto('/')
    await page.evaluate(() => localStorage.clear())
    await page.reload()
    // ChatView redirects to /setup when setupComplete is false
    await expect(page).toHaveURL('/setup')
  })
})

test.describe('404 page', () => {
  test('unknown route shows 404 message', async ({ page }) => {
    await page.goto('/this-does-not-exist')
    await expect(page.locator('.code')).toContainText('404')
  })
})
