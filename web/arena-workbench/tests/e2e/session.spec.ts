import { expect, test } from '@playwright/test';

for (const hostname of ['localhost', '127.0.0.1']) {
  test(`session reconnect and live observation through ${hostname}`, async ({ page }, testInfo) => {
    const base = new URL(process.env.WORKBENCH_BASE_URL ?? 'http://127.0.0.1:3001');
    base.hostname = hostname;
    const url = `${base.origin}/workspaces/default?filter=all`;
    const submitted: string[] = [];
    const pageErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    page.on('request', (request) => {
      if (request.method() === 'POST' && /\/api\/(jobs|editor\/(generate|snapshots|save))$/.test(new URL(request.url()).pathname)) {
        submitted.push(request.url());
      }
    });
    // Inject only a transport failure; successful sessions/data come from the real API.
    let failFirst = true;
    await page.route('**/api/sessions', (route) => {
      if (failFirst) {
        failFirst = false;
        return route.abort('connectionrefused');
      }
      return route.continue();
    });
    await page.goto(url);
    const reconnect = page.getByRole('button', { name: 'Reconnect session', exact: true });
    await expect(reconnect).toBeEnabled();
    await expect(page.locator('.connection')).toHaveText('Disconnected');
    await reconnect.click();
    await expect(page.locator('.connection')).toHaveText('Live · shared stream', { timeout: 10_000 });
    await expect(page.getByText('Schema valid', { exact: true })).toBeVisible();
    await expect(page.locator('.notice.error')).toHaveCount(0);
    await expect(page.locator('.transport-note')).toHaveCount(0);
    expect((await page.request.get(`${base.origin}/api/session`)).status()).toBe(200);
    expect((await page.request.get(`${base.origin}/api/workspaces/default`)).status()).toBe(200);
    await page.getByRole('link', { name: 'Neo4j query', exact: true }).click();
    await expect(page.locator('.connection')).toHaveText('Live · shared stream');
    await page.getByRole('link', { name: 'Environment editor', exact: true }).click();
    await page.reload();
    await expect(page.locator('.connection')).toHaveText('Live · shared stream');
    await expect(page.getByText('Schema valid', { exact: true })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`${hostname}-connected.png`), fullPage: true });
    expect(submitted).toEqual([]);
    expect(pageErrors).toEqual([]);
  });
}
