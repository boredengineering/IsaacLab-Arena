import { expect, test, type Page } from '@playwright/test';

async function ready(page: Page) {
  await page.goto('/developer/diagnostics');
  await expect(page.getByRole('heading', { name: 'Arena workspace' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'End session' })).toBeVisible();
}
async function enableDiagnostics(page: Page) {
  test.skip(
    process.env.WORKBENCH_E2E_DIAGNOSTICS !== '1',
    'Set WORKBENCH_E2E_DIAGNOSTICS=1 to authorize bounded diagnostic jobs.',
  );
  const health = await (await page.request.get('/api/health')).json();
  expect(health.capabilities.diagnostic, 'API must explicitly enable --diagnostics').toBe(true);
  await page.getByRole('checkbox', { name: /enable diagnostic controls/i }).check();
}
async function jobs(page: Page) {
  return (await (await page.request.get('/api/jobs')).json()).jobs as {
    id: string;
    status: string;
  }[];
}

test('deep links and unavailable research controls never launch jobs', async ({ page }) => {
  let submissions = 0;
  page.on('request', (req) => {
    if (new URL(req.url()).pathname === '/api/jobs' && req.method() === 'POST') submissions++;
  });
  await page.goto('/jobs/not-a-real-job');
  await expect(page.getByRole('heading', { name: 'Job not found' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Environment editor' })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Job not found' })).toBeVisible();
  expect(submissions).toBe(0);
});

test('two tabs share a worker; real progress crosses a heartbeat and reload never resubmits', async ({
  page,
  context,
  browser,
}) => {
  await ready(page);
  await enableDiagnostics(page);
  const before = new Set((await jobs(page)).map((j) => j.id));
  await page.getByLabel('Steps', { exact: true }).fill('4');
  await page.getByLabel('Delay per step (s)').fill('5');
  const accepted = page.waitForResponse(
    (r) => new URL(r.url()).pathname === '/api/jobs' && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Run integration test' }).click();
  const response = await accepted;
  expect(response.status()).toBe(202);
  const submitted = await response.json();
  const headers = await response.request().allHeaders();
  expect(headers.origin).toBe(new URL(page.url()).origin);
  expect(headers['x-csrf-token']).toBeTruthy();
  await expect(page).toHaveURL(new RegExp(`/jobs/${submitted.id}`));
  const other = await context.newPage();
  await other.goto(`/jobs/${submitted.id}`);
  await expect(other.getByText('Live · shared stream', { exact: true })).toBeVisible();
  await enableDiagnostics(other);
  const secondResponse = other.waitForResponse(
    (r) => new URL(r.url()).pathname === '/api/jobs' && r.request().method() === 'POST',
  );
  await other.getByRole('button', { name: 'Run integration test' }).click();
  const second = await (await secondResponse).json();
  await expect(other).toHaveURL(new RegExp(`/jobs/${second.id}`));
  const cdp = await browser.newBrowserCDPSession();
  const targets = await cdp.send('Target.getTargets');
  expect(
    targets.targetInfos.filter(
      (t) => t.type === 'shared_worker' && t.url.includes('events.shared-worker'),
    ),
  ).toHaveLength(1);
  const initialStage = await page.getByTestId('job-stage').textContent();
  await expect(page.getByTestId('job-stage')).not.toHaveText(initialStage ?? '', {
    timeout: 12_000,
  });
  await page.reload();
  await expect(page.getByTestId('job-result')).toBeVisible({ timeout: 35_000 });
  await expect(other.getByTestId('job-result')).toBeVisible();
  const created = (await jobs(page)).filter((j) => !before.has(j.id));
  expect(created.map((j) => j.id).sort()).toEqual([submitted.id, second.id].sort());
  await cdp.detach();
});

test('an ambiguous accepted POST is retained across reload and explicitly retried with the same key', async ({
  page,
}) => {
  await ready(page);
  await enableDiagnostics(page);
  const before = new Set((await jobs(page)).map((j) => j.id));
  let first = true;
  let acceptedId = '';
  const requests: string[] = [];
  await page.route('**/api/jobs', async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    requests.push(route.request().postData()!);
    if (first) {
      first = false;
      const response = await route.fetch();
      expect(response.status()).toBe(202);
      acceptedId = (await response.json()).id;
      await route.abort('failed');
    } else await route.continue();
  });
  await page.getByRole('button', { name: 'Run integration test' }).click();
  await expect(page.getByRole('button', { name: 'Retry retained request' })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('button', { name: 'Retry retained request' })).toBeVisible();
  expect(requests).toHaveLength(1);
  await enableDiagnostics(page);
  await page.getByRole('button', { name: 'Retry retained request' }).click();
  await expect(page).toHaveURL(new RegExp(`/jobs/${acceptedId}`));
  expect(requests).toHaveLength(2);
  expect(requests[0]).toBe(requests[1]);
  expect((await jobs(page)).filter((j) => !before.has(j.id)).map((j) => j.id)).toEqual([
    acceptedId,
  ]);
});

test('revocation reaches another tab and requires an explicit replacement session', async ({
  page,
  context,
}) => {
  await ready(page);
  const other = await context.newPage();
  await ready(other);
  await expect(other.getByText('Live · shared stream', { exact: true })).toBeVisible();
  const before = (await jobs(page)).map((j) => j.id).sort();
  await page.getByRole('button', { name: 'End session' }).click();
  await expect(other.getByText('Session expired or revoked', { exact: true })).toBeVisible();
  await expect(other.getByRole('button', { name: 'Run integration test' })).toBeDisabled();
  await other.getByRole('button', { name: 'Reconnect session' }).click();
  await expect(other.getByRole('button', { name: 'End session' })).toBeVisible();
  expect((await jobs(other)).map((j) => j.id).sort()).toEqual(before);
});

test('unsupported SharedWorker uses bounded polling and stops after terminal results', async ({
  context,
  page,
}) => {
  await context.addInitScript(() =>
    Object.defineProperty(globalThis, 'SharedWorker', { value: undefined }),
  );
  await ready(page);
  await enableDiagnostics(page);
  let reads = 0;
  page.on('request', (r) => {
    if (new URL(r.url()).pathname === '/api/workspaces/default') reads++;
  });
  await page.getByRole('button', { name: 'Run integration test' }).click();
  await expect(page.getByText('Degraded · status polling', { exact: true })).toBeVisible();
  await expect(page.getByTestId('job-result')).toBeVisible();
  const count = reads;
  await page.waitForTimeout(5500);
  expect(reads).toBe(count);
});
