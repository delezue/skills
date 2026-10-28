// Independent check: read what a real browser shows on MoneyDJ, through the DOM (not the skill's JSON/regex path).
// Needs Node.js + Playwright. Looked up in: $PLAYWRIGHT_PATH, a normal require('playwright'),
// then ~/.claude/skills/playwright-skill/node_modules/playwright.
const fs = require('fs');
const os = require('os');
const path = require('path');
function loadPlaywright() {
  const tries = [process.env.PLAYWRIGHT_PATH, 'playwright',
    path.join(os.homedir(), '.claude', 'skills', 'playwright-skill', 'node_modules', 'playwright')].filter(Boolean);
  for (const t of tries) { try { return require(t); } catch (e) { /* next */ } }
  console.error('Playwright not found. Install it once:  npm i -g playwright && npx playwright install chromium\n' +
    'or set PLAYWRIGHT_PATH to a folder that contains node_modules/playwright.');
  process.exit(2);
}
const { chromium } = loadPlaywright();
const SAMPLE = +(process.argv[2] || 40);

(async () => {
  const b = await chromium.launch();
  const pg = await b.newPage();
  // 1. category page rendered by its own JS
  await pg.goto('https://www.moneydj.com/iQuote/iQuoteFundCatFund.djhtm?A=2&B=1&C=47', { waitUntil: 'domcontentloaded', timeout: 90000 });
  await pg.waitForFunction(() => document.querySelectorAll('#oMainTable tbody tr a.product_name_fund').length > 50, null, { timeout: 90000 });
  const head = await pg.$$eval('#oMainTable thead tr:last-child th, #oMainTable thead tr:last-child td', ths => ths.map(t => t.textContent.trim()));
  const cat = await pg.$$eval('#oMainTable tbody tr', trs => trs.map(tr => {
    const tds = [...tr.querySelectorAll('td')].map(td => td.textContent.trim());
    const a = tr.querySelector('a.product_name_fund');
    return a ? { href: a.getAttribute('href'), name: a.textContent.trim(), cells: tds.slice(2) } : null;
  }).filter(Boolean));
  // 2. random sample of fund pages, NAV table read by DOM
  const codes = cat.map(r => r.href);
  for (let i = codes.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [codes[i], codes[j]] = [codes[j], codes[i]]; }
  const det = [];
  for (const href of codes.slice(0, SAMPLE)) {
    const p = await b.newPage();
    try {
      await p.goto('https://www.moneydj.com' + href, { waitUntil: 'domcontentloaded', timeout: 60000 });
      const v = await p.evaluate(() => {
        const td = [...document.querySelectorAll('td')].find(t => t.textContent.trim() === '淨值日期');
        if (!td) return null;
        const hdr = td.closest('tr'), row = hdr.nextElementSibling;
        return { labels: [...hdr.children].map(c => c.textContent.trim()), values: [...row.children].map(c => c.textContent.trim()) };
      });
      det.push({ href, ...v });
    } catch (e) { det.push({ href, error: String(e).slice(0, 120) }); }
    await p.close();
  }
  fs.writeFileSync('browser_data.json', JSON.stringify({ head, cat, det }, null, 1));
  console.log('header', JSON.stringify(head));
  console.log('category rows', cat.length, 'detail sampled', det.length);
  await b.close();
})();
