/**
 * Playwright e2e — full session setup wizard flow.
 *
 * Mocks:
 *  - /api/v1/session/connectivity → { ok: true }
 *  - /api/v1/session/auth/init    → { authUrl: 'about:blank', state: 'test123' }
 *  - /api/v1/session/auth/status  → { status: 'complete' }
 */
import { expect, test } from '@playwright/test'

test.describe('Session setup wizard', () => {
  test.beforeEach(async ({ page }) => {
    // Intercept backend calls so the wizard can progress without a real Grafana
    await page.route('**/api/v1/session/connectivity', (route) =>
      route.fulfill({ json: { ok: true, latencyMs: 12 } }),
    )
    await page.route('**/api/v1/session/auth/init', (route) =>
      route.fulfill({ json: { authUrl: 'about:blank', state: 'test123' } }),
    )
    await page.route('**/api/v1/session/auth/status**', (route) =>
      route.fulfill({ json: { status: 'complete' } }),
    )

    // Clear localStorage so each test starts fresh
    await page.goto('/setup')
    await page.evaluate(() => localStorage.clear())
    await page.reload()
  })

  test('shows step 1 on fresh load', async ({ page }) => {
    await expect(page.locator('#grafana-url')).toBeVisible()
    await expect(page.locator('text=Connect to Grafana')).toBeVisible()
  })

  test('step 1: invalid URL keeps Next disabled', async ({ page }) => {
    await page.fill('#grafana-url', 'not-a-url')
    const nextBtn = page.getByRole('button', { name: /next/i })
    await expect(nextBtn).toBeDisabled()
  })

  test('step 1: valid URL + successful connectivity test enables Next', async ({ page }) => {
    await page.fill('#grafana-url', 'https://grafana.example.com')
    await page.getByRole('button', { name: /test connection/i }).click()
    await expect(page.locator('text=Connected successfully')).toBeVisible()
    await expect(page.getByRole('button', { name: /next/i })).toBeEnabled()
  })

  test('step 1 → step 2: clicking Next shows auth step', async ({ page }) => {
    await page.fill('#grafana-url', 'https://grafana.example.com')
    await page.getByRole('button', { name: /test connection/i }).click()
    await page.getByRole('button', { name: /next/i }).click()
    await expect(page.locator('text=Authenticate with Grafana')).toBeVisible()
  })

  test('step 2: auth poll completes and shows success', async ({ page }) => {
    // Go directly to step 2 by manipulating localStorage
    await page.evaluate(() => {
      localStorage.setItem('setup.step', '2')
      localStorage.setItem('setup.grafanaUrl', 'https://grafana.example.com')
    })
    await page.reload()

    await page.getByRole('button', { name: /open grafana login/i }).click()
    // Poll fires after 2s; advance fake time or just wait
    await expect(page.locator('text=Authenticated successfully')).toBeVisible({ timeout: 8000 })
  })

  test('full wizard: completes all 4 steps and redirects to /', async ({ page }) => {
    // Step 1
    await page.fill('#grafana-url', 'https://grafana.example.com')
    await page.getByRole('button', { name: /test connection/i }).click()
    await page.getByRole('button', { name: /next/i }).click()

    // Step 2
    await page.getByRole('button', { name: /open grafana login/i }).click()
    await expect(page.locator('text=Authenticated successfully')).toBeVisible({ timeout: 8000 })
    await page.getByRole('button', { name: /next/i }).click()

    // Step 3
    await expect(page.locator('text=Context')).toBeVisible()
    await page.fill('#namespace', 'production')
    await page.getByRole('button', { name: /next/i }).click()

    // Step 4 — confirm
    await expect(page.locator('text=Confirm setup')).toBeVisible()
    await expect(page.locator('text=https://grafana.example.com')).toBeVisible()
    await page.getByRole('button', { name: /start session/i }).click()

    // Should redirect to chat
    await expect(page).toHaveURL('/')
  })

  test('Back button returns to previous step', async ({ page }) => {
    await page.fill('#grafana-url', 'https://grafana.example.com')
    await page.getByRole('button', { name: /test connection/i }).click()
    await page.getByRole('button', { name: /next/i }).click()
    // Now on step 2
    await page.getByRole('button', { name: /back/i }).click()
    await expect(page.locator('#grafana-url')).toBeVisible()
  })
})
