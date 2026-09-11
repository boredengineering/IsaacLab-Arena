import { expect, test } from '@playwright/test';

// Exercise appearance against the real API without starting generation or rendering.
test('theme changes preserve edits and survive navigation and reload', async ({ page }, testInfo) => {
  const mutations: string[] = [];
  page.on('request', (request) => {
    if (request.method() === 'POST' && /\/api\/(jobs|editor\/(generate|snapshots|save))$/.test(new URL(request.url()).pathname)) {
      mutations.push(request.url());
    }
  });
  await page.goto('/');
  await expect(page.getByText('Schema valid', { exact: true })).toBeVisible();
  const toggle = page.getByRole('switch', { name: 'Dark mode' });
  const navigation = await page.getByRole('navigation', { name: 'Workspace navigation' }).boundingBox();
  const toggleBox = await toggle.boundingBox();
  expect(toggleBox!.x).toBeGreaterThan(navigation!.x + navigation!.width);
  const editor = page.getByRole('textbox', { name: 'YAML editor' });
  const originalEditor = await page.locator('.cm-editor').elementHandle();
  await page.locator('.prompt-section textarea').fill('Keep this unsaved prompt');
  await editor.click();
  await page.keyboard.press('ControlOrMeta+Home');
  await page.keyboard.insertText('# theme draft check ');
  await toggle.focus();
  await page.keyboard.press('Space');
  await expect(toggle).toBeChecked();
  await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(17, 24, 21)');
  await expect(editor).toContainText('theme draft check');
  expect(await originalEditor!.evaluate((element) => element === document.querySelector('.cm-editor'))).toBe(true);
  await expect(page.getByText('Schema valid', { exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('editor-dark.png'), fullPage: true });
  await page.getByRole('link', { name: 'Neo4j query', exact: true }).click();
  await expect(toggle).toBeChecked();
  await page.getByRole('link', { name: 'Environment editor', exact: true }).click();
  await expect(editor).toContainText('theme draft check');
  await expect(page.locator('.prompt-section textarea')).toHaveValue('Keep this unsaved prompt');
  await page.reload();
  await expect(toggle).toBeChecked();
  await toggle.focus();
  await page.keyboard.press('Enter');
  await expect(toggle).not.toBeChecked();
  await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(250, 251, 249)');
  await page.reload();
  await expect(toggle).not.toBeChecked();
  await page.screenshot({ path: testInfo.outputPath('editor-light.png'), fullPage: true });
  expect(mutations).toEqual([]);
});

test('theme control remains visible and usable in the top sidebar on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  const toggle = page.getByRole('switch', { name: 'Dark mode' });
  await expect(toggle).toBeVisible();
  const box = await toggle.boundingBox();
  expect(box!.y).toBeLessThan(100);
  expect(box!.x).toBeGreaterThan(250);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  await toggle.click();
  await expect(toggle).toBeChecked();
});
