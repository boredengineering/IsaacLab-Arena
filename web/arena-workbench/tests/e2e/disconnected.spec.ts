import { expect, test } from '@playwright/test';
// This suite needs only the real static app server. API failures are explicitly injected, not research fixtures.
for (const width of [1440, 390]) {
  test(`disconnected shell is usable at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1050 });
    await page.route('**/api/**', (route) => route.abort('connectionrefused'));
    await page.goto('/workspaces/default');
    await expect(
      page.getByRole('heading', { name: 'ArenaEnvGraphSpec live editor' }),
    ).toBeVisible();
    await expect(page.getByText('Disconnected', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Reconnect session' })).toBeEnabled();
    await expect(page.getByRole('button', { name: 'Generate spec' })).toBeDisabled();
    await expect(page.getByRole('button', { name: 'Render snapshots' })).toBeDisabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({ path: `test-results/disconnected-${width}.png`, fullPage: true });
  });
}
