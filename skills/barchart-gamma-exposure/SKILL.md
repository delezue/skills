---
name: barchart-gamma-exposure
description: 爬取 Barchart 個股 Gamma Exposure (GEX) 頁面，輸出日期、股價、漲跌幅、gamma flip point、put wall、call wall。Use when the user gives a US ticker (e.g. TSM, NVDA, SPY) and asks for gamma exposure / GEX / gamma flip / put wall / call wall / barchart gamma，或「TSM gamma」「美股 GEX 關鍵價位」。
---

# Barchart Gamma Exposure 關鍵價位

來源頁面：`https://www.barchart.com/stocks/quotes/<SYMBOL>/gamma-exposure`

## 安裝

1. 把 `skills/barchart-gamma-exposure/` 複製到 `~/.claude/skills/`。
2. 需要 Node.js 與 Playwright Chromium，下面兩種擇一：
   - 已裝 `playwright-skill`（`~/.claude/skills/playwright-skill/node_modules/playwright`）→ 免安裝，腳本會自動找到。
   - 否則在任一可被 `require` 解析的位置執行：`npm i playwright && npx playwright install chromium`。

## 執行

```bash
node ~/.claude/skills/barchart-gamma-exposure/scripts/fetch_gex.js TSM
node ".../fetch_gex.js" TSM NVDA SPY        # 多檔
node ".../fetch_gex.js" TSM --json          # JSON 輸出
node ".../fetch_gex.js" TSM --headed        # 開視窗除錯
```

單檔約 15–30 秒。輸入不帶參數時預設 TSM。

## 輸出格式（照此回覆使用者）

```
輸入 : TSM
日期 : 10/12/26
股價 : 444.35
漲跌幅 : -1.98%
gamma flip point :  435.41
put wall : 420.00
call wall : 450.00
```

可補一行解讀：股價在 flip point 之上 = 正 gamma（造市商避險抑制波動），之下 = 負 gamma（波動放大）；put wall / call wall 為支撐 / 壓力參考。

## 資料位置（頁面改版時從這裡修）

- 日期/股價/漲跌幅：`.symbol-header-info` 的 `data-ng-init="init({...})"` JSON → `tradeTime`、`lastPrice`、`percentChange`、`priceChange`；備援 `.pricechangerow .last-change`。
- Flip / Wall：`#gex-data .gex-title` 文字 —「gamma flip point is X」「put wall is Y」「call wall is Z」（regex 會去掉句尾句點）。
- 個別履約價 gamma 原始資料在 `<script id="barchart-www-inline-gamma-levels">` JSON，及 API `/proxies/core-api/v1/options/get?symbols=...`（需 XSRF cookie）。

## 陷阱

- **AWS WAF JS challenge**：curl / requests / curl_cffi 都只拿到 HTTP 202 + `challenge.js` 空頁，必須用真瀏覽器。腳本用 Playwright Chromium headless（從 `~/.claude/skills/playwright-skill/node_modules/playwright` 載入），已驗證 headless 可通過。
- 若 `waitForSelector('#gex-data .gex-title')` 逾時：可能被 WAF/reCAPTCHA 擋或代號無選擇權 → 用 `--headed` 看畫面。
- 日期是 Barchart 的 `tradeTime`（美東交易日，MM/DD/YY），盤中為即時價、flip/wall 以前一日 OI 計算（OI 每日更新一次）。
- 只支援 stocks/ETF 路徑（`/stocks/quotes/`）；指數期貨等不同路徑不適用。
