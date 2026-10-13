#!/usr/bin/env node
// Barchart Gamma Exposure scraper
// Usage: node fetch_gex.js TSM [NVDA ...] [--json] [--headed]
// Output per symbol: date, price, change %, gamma flip point, put wall, call wall.
//
// barchart.com sits behind an AWS WAF JavaScript challenge (plain HTTP gets a
// 202 + challenge.js page), so a real browser (Playwright Chromium) is used.
const path = require('path');

function loadPlaywright() {
  const candidates = [
    'playwright',
    path.join(process.env.USERPROFILE || process.env.HOME || '', '.claude/skills/playwright-skill/node_modules/playwright'),
  ];
  for (const c of candidates) { try { return require(c); } catch (e) {} }
  console.error('Playwright not found. Install: npm i playwright && npx playwright install chromium');
  process.exit(2);
}
const { chromium } = loadPlaywright();

const args = process.argv.slice(2);
const asJson = args.includes('--json');
const headed = args.includes('--headed');
const symbols = args.filter(a => !a.startsWith('--')).map(s => s.toUpperCase());
if (!symbols.length) symbols.push('TSM');

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36';

async function scrape(page, sym) {
  const url = `https://www.barchart.com/stocks/quotes/${encodeURIComponent(sym)}/gamma-exposure`;
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  // WAF challenge reloads the page once; wait for the real content.
  await page.waitForSelector('#gex-data .gex-title', { timeout: 45000 });

  return page.evaluate(() => {
    const out = {};
    // Header quote: data-ng-init="init({...})" on .symbol-header-info
    const hdr = document.querySelector('.symbol-header-info[data-ng-init]');
    if (hdr) {
      const m = hdr.getAttribute('data-ng-init').match(/init\((\{[\s\S]*\})\)/);
      if (m) {
        try {
          const j = JSON.parse(m[1]);
          out.name = j.symbolName; out.date = j.tradeTime;
          out.price = j.lastPrice; out.change = j.priceChange; out.changePct = j.percentChange;
        } catch (e) {}
      }
    }
    // Fallback to the visible header spans
    const txt = sel => { const e = document.querySelector(sel); return e ? e.textContent.trim() : null; };
    out.price = out.price || txt('.pricechangerow .last-change');
    out.date = out.date || txt('.pricechangerow .symbol-trade-time');

    const g = document.querySelector('#gex-data .gex-title');
    const t = g ? g.textContent.replace(/\s+/g, ' ') : '';
    const num = re => { const m = t.match(re); return m ? m[1].replace(/[.,]+$/, "") : null; };
    out.gammaFlip = num(/gamma flip point is\s*([\d,.]+)/i);
    out.putWall = num(/put wall is\s*([\d,.]+)/i);
    out.callWall = num(/call wall is\s*([\d,.]+)/i);
    return out;
  });
}

(async () => {
  const browser = await chromium.launch({ headless: !headed });
  const ctx = await browser.newContext({ userAgent: UA, viewport: { width: 1400, height: 1000 }, locale: 'en-US' });
  // Skip heavy ad/media assets: faster and fewer hangs.
  await ctx.route('**/*', r => ['image', 'media', 'font'].includes(r.request().resourceType()) ? r.abort() : r.continue());
  const page = await ctx.newPage();
  const results = [];
  for (const sym of symbols) {
    let res = null, err = null;
    for (let attempt = 1; attempt <= 2 && !res; attempt++) {
      try { res = await scrape(page, sym); } catch (e) { err = e.message.split('\n')[0]; }
    }
    results.push(res ? { symbol: sym, ...res } : { symbol: sym, error: err || 'no data' });
  }
  await browser.close();

  if (asJson) { console.log(JSON.stringify(results, null, 2)); return; }
  for (const r of results) {
    console.log(`輸入 : ${r.symbol}${r.name ? '  (' + r.name + ')' : ''}`);
    if (r.error) { console.log(`錯誤 : ${r.error}\n`); continue; }
    console.log(`日期 : ${r.date ?? 'N/A'}`);
    console.log(`股價 : ${r.price ?? 'N/A'}`);
    console.log(`漲跌幅 : ${r.changePct ?? 'N/A'}${r.change ? '  (' + r.change + ')' : ''}`);
    console.log(`gamma flip point :  ${r.gammaFlip ?? 'N/A'}`);
    console.log(`put wall : ${r.putWall ?? 'N/A'}`);
    console.log(`call wall : ${r.callWall ?? 'N/A'}\n`);
  }
  if (results.some(r => r.error)) process.exitCode = 1;
})();
