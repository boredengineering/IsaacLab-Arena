import { expect, test } from '@playwright/test';

// Use only synthetic markers here. Never record real credential-entry sessions.
test.use({ trace: 'off', screenshot: 'off', video: 'off' });

test('temporary provider key stays out of public state and is explicitly forgotten', async ({ page, browser, baseURL }) => {
  const marker = 'dummy-browser-only-provider-key-not-a-real-secret';
  let generationRequests = 0;
  await page.route('**/api/editor/generate', async route => {
    generationRequests++;
    await route.abort();
  });
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'End session' })).toBeVisible();
  const panel = page.getByRole('region', { name: 'Temporary provider settings' });
  await expect(panel).toBeVisible();
  const initial = await page.request.get('/api/model-settings');
  expect(initial.ok()).toBe(true);
  expect((await initial.json()).source).not.toBe('session');
  const beforeJobs = await (await page.request.get('/api/jobs')).json();
  const editor = page.getByRole('textbox', { name: 'YAML editor' });
  await expect(page.getByText('Schema valid', { exact: true })).toBeVisible();
  const sourceText = await editor.innerText();

  await panel.getByLabel('Provider', { exact: true }).selectOption('openai');
  await panel.getByLabel('Model', { exact: true }).fill('dummy-no-inference-model');
  const expiration = panel.getByRole('combobox', { name: 'Key expiration' });
  await expect(expiration).toHaveValue('30');
  await expiration.selectOption('15');
  const password = panel.getByLabel('API key', { exact: true });
  await expect(password).toHaveAttribute('type', 'password');
  await expect(panel.getByRole('button', { name: 'Save temporary key' })).toBeDisabled();
  // Consent changes clear the input, so paste only after consent is selected.
  await panel.getByRole('checkbox').check();
  await password.fill(marker);
  const saved = page.waitForResponse(r => new URL(r.url()).pathname === '/api/model-settings'
    && r.request().method() === 'PUT');
  const savedAt = Date.now() / 1000;
  await panel.getByRole('button', { name: 'Save temporary key' }).click();
  const savedResponse = await saved;
  expect(savedResponse.ok()).toBe(true);
  expect(await savedResponse.text()).not.toContain(marker);
  await expect(password).toHaveValue('');
  await expect(panel.getByText(/Temporary key active/)).toBeVisible();
  expect(await editor.innerText()).toBe(sourceText);
  const configuredResponse = await page.request.get('/api/model-settings');
  const configured = await configuredResponse.json();
  expect(configured.source).toBe('session');
  expect(configured.provider).toBe('openai');
  expect(configured.model).toBe('dummy-no-inference-model');
  expect(configured.credential_ref).toBeTruthy();
  expect(configured.expires_at).toBeGreaterThanOrEqual(savedAt + 15 * 60 - 1);
  expect(configured.expires_at).toBeLessThanOrEqual(Date.now() / 1000 + 15 * 60 + 1);
  await expiration.selectOption('120');
  const unchanged = await (await page.request.get('/api/model-settings')).json();
  expect(unchanged.expires_at).toBe(configured.expires_at);
  expect(unchanged.credential_ref).toBe(configured.credential_ref);
  expect(JSON.stringify(configured)).not.toContain(marker);

  const stored = await page.evaluate(() => JSON.stringify({
    local: Object.fromEntries(Object.entries(localStorage)),
    session: Object.fromEntries(Object.entries(sessionStorage)),
  }));
  expect(stored).not.toContain(marker);
  expect(await page.locator('body').innerText()).not.toContain(marker);
  expect(JSON.stringify(await (await page.request.get('/api/jobs')).json())).not.toContain(marker);

  // A separate browser session must not inherit this session's temporary key.
  const other = await browser.newContext({ baseURL });
  try {
    const second = await other.newPage();
    await second.goto('/');
    await expect(second.getByRole('button', { name: 'End session' })).toBeVisible();
    const status = await (await second.request.get('/api/model-settings')).json();
    expect(status.source).not.toBe('session');
    expect(status.credential_ref).toBeNull();
  } finally {
    await other.close();
  }

  await page.reload();
  await expect(panel.getByText(/Temporary key active/)).toBeVisible();
  await expect(password).toHaveValue('');
  await panel.getByRole('button', { name: 'Forget key' }).click();
  await expect(panel.getByText(/Temporary key active/)).toHaveCount(0);
  const forgotten = await (await page.request.get('/api/model-settings')).json();
  expect(forgotten.source).not.toBe('session');
  expect(forgotten.credential_ref).toBeNull();
  const afterJobs = await (await page.request.get('/api/jobs')).json();
  expect(afterJobs.jobs.map((j: { id: string }) => j.id)).toEqual(beforeJobs.jobs.map((j: { id: string }) => j.id));
  expect(generationRequests).toBe(0);
});
