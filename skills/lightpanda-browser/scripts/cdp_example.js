/**
 * Lightpanda CDP Automation Example (Node.js)
 * Connects to Lightpanda CDP server (ws://localhost:9222) via Puppeteer or Playwright.
 */

const http = require('http');

/**
 * Check if Lightpanda CDP daemon is available on port 9222
 * @param {string} host 
 * @param {number} port 
 * @returns {Promise<boolean>}
 */
function checkCdpAvailable(host = '127.0.0.1', port = 9222) {
  return new Promise((resolve) => {
    const req = http.get(`http://${host}:${port}/json/version`, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try {
          const info = JSON.parse(data);
          console.log(`[Lightpanda CDP] Connected: ${info.Browser} (${info['Lightpanda-Version'] || info['Protocol-Version']})`);
          resolve(true);
        } catch (e) {
          resolve(false);
        }
      });
    });
    req.on('error', () => resolve(false));
    req.setTimeout(2000, () => {
      req.destroy();
      resolve(false);
    });
  });
}

/**
 * Example Playwright / Puppeteer usage snippet:
 * 
 * const puppeteer = require('puppeteer-core');
 * async function scrapeWithPuppeteer() {
 *   const browser = await puppeteer.connect({ browserURL: 'http://127.0.0.1:9222' });
 *   const page = await browser.newPage();
 *   await page.goto('https://example.com');
 *   const title = await page.title();
 *   console.log('Page Title:', title);
 *   await browser.close();
 * }
 */

async function main() {
  console.log('[Lightpanda] Probing CDP Server at 127.0.0.1:9222...');
  const isAvailable = await checkCdpAvailable();
  if (isAvailable) {
    console.log('[Lightpanda] CDP Server is READY for automation.');
  } else {
    console.log('[Lightpanda] CDP Server is NOT running. Start it using:');
    console.log('  python lightpanda_client.py serve --port 9222');
    console.log('  or in WSL: ~/.local/bin/lightpanda serve --host 0.0.0.0 --port 9222');
  }
}

if (require.main === module) {
  main().catch(console.error);
}

module.exports = { checkCdpAvailable };
