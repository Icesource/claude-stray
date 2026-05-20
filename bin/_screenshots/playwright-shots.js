const { chromium } = require('playwright');
const TARGET = 'http://127.0.0.1:9876/';
const OUT_PREFIX = process.env.OUT_PREFIX || '/tmp/clean-shot';

(async () => {
  const browser = await chromium.launch({ headless: false });
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  await page.goto(TARGET, { waitUntil: 'networkidle' });
  await page.waitForSelector('.tips-bubble:not([hidden])', { timeout: 8000 }).catch(() => {});

  // Hide lifecycle banner for clean promo shots (even when paused)
  await page.addStyleTag({ content: `
    #lifecycle-banner { display: none !important; }
  ` });
  await page.waitForTimeout(400);

  await page.screenshot({ path: `${OUT_PREFIX}1-overview.png` });
  console.log('shot1: overview');

  const card = page.locator('article.card').first();
  await card.scrollIntoViewIfNeeded();
  await page.waitForTimeout(200);
  const cbox = await card.boundingBox();
  if (cbox) {
    await page.screenshot({
      path: `${OUT_PREFIX}2-card-detail.png`,
      clip: {
        x: Math.max(0, cbox.x - 20),
        y: Math.max(0, cbox.y - 20),
        width: Math.min(1600, cbox.width + 40),
        height: cbox.height + 40,
      },
    });
    console.log('shot2: card detail');
  }

  const bubble = page.locator('.tips-bubble');
  const bbox = await bubble.boundingBox();
  if (bbox) {
    await page.screenshot({
      path: `${OUT_PREFIX}3-tips-bubble.png`,
      clip: {
        x: Math.max(0, bbox.x - 30),
        y: Math.max(0, bbox.y - 30),
        width: bbox.width + 60,
        height: bbox.height + 60,
      },
    });
    console.log('shot3: tips bubble');
  }

  const weeklyBtn = page.locator('#dw-weekly-btn');
  if (await weeklyBtn.count()) {
    await weeklyBtn.scrollIntoViewIfNeeded();
    await page.waitForTimeout(200);
    await weeklyBtn.click({ timeout: 5000 }).catch(e => console.log('weekly click skipped:', e.message));
    await page.waitForTimeout(400);
    if (await page.locator('.weekly-modal').count()) {
      await page.screenshot({ path: `${OUT_PREFIX}4-weekly-modal.png` });
      console.log('shot4: weekly modal');
      await page.keyboard.press('Escape');
    } else {
      console.log('shot4: skipped (modal didn\'t open)');
    }
  }

  const activeChip = page.locator('button.chip[data-status="active"]');
  if (await activeChip.count()) {
    await activeChip.click();
    await page.waitForTimeout(300);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(200);
    await page.screenshot({ path: `${OUT_PREFIX}5-filter-active.png` });
    console.log('shot5: filter active');
  }

  await browser.close();
  console.log('done');
})();
