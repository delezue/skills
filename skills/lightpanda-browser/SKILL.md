---
name: lightpanda-browser
description: >-
  基於 Zig 開發的極速輕量級無頭瀏覽器 Lightpanda (16x 記憶體節省、9x 冷啟動加速、內建 V8 引擎與完整 CDP/MCP 支援)。
  可秒級抓取 JavaScript 動態渲染網頁並轉換為 Markdown、HTML、結構化資料 (JSON-LD/Meta/OpenGraph)，
  或作為 CDP Server (port 9222) 供 Puppeteer/Playwright 與 AI Agent 進行即時瀏覽與自動化操作。
  當使用者提到「Lightpanda」、「lightpanda-browser」、「極速無頭瀏覽器」、「輕量網頁抓取」、「CDP 爬蟲」或需要高速抓取 JS 渲染網頁時觸發。
---

# Lightpanda 極速輕量級無頭瀏覽器技能 (`lightpanda-browser`)

本技能整合由 Zig 語言打造的次世代開源無頭瀏覽器 **Lightpanda**（[GitHub: lightpanda-io/browser](https://github.com/lightpanda-io/browser)）。不同於傳統龐大臃腫的 Chromium，Lightpanda 專為 AI Agent、網頁資料擷取與自動化打造，記憶體消耗僅為 Chrome 的 **1/16**，啟動速度提升 **9 倍**，並具備完整現代 Web API 與 V8 JavaScript 執行能力。

---

## 1. 核心架構與三大模式

Lightpanda 支援三種核心運作架構：

```
┌────────────────────────────────────────────────────────┐
│               AI Agent / Quantitative App              │
└────────┬───────────────────┬───────────────────┬───────┘
         │ (1) Direct CLI    │ (2) CDP Protocol  │ (3) MCP Protocol
         ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ lightpanda      │ │ Puppeteer /     │ │ Claude / AGY    │
│ fetch <url>     │ │ Playwright      │ │ Model Context   │
│ --dump markdown │ │ ws://127.0.0.1  │ │ Protocol (:8080)│
└────────┬────────┘ └────────┬────────┘ └────────┬────────┘
         │                   │                   │
         └───────────────────┼───────────────────┘
                             ▼
         ┌───────────────────────────────────────┐
         │       Lightpanda Engine (v1.0.2)      │
         │  (Zig + V8 Engine + Headless Network) │
         └───────────────────────────────────────┘
```

1. **直接擷取模式 (`fetch`)**：
   * 無需常駐服務，單次命令行秒級執行目標頁面之 JavaScript，直接輸出清洗後的 **Markdown**、**HTML**、**結構化資料 (JSON-LD / OpenGraph)** 或 **Semantic Tree**。
2. **CDP 伺服器模式 (`serve`)**：
   * 啟動 WebSocket Chrome DevTools Protocol (`ws://127.0.0.1:9222`)，相容標準 Puppeteer / Playwright 代碼，作為極低開銷的 Chromium 替代品。
3. **MCP 服務模式 (`mcp`)**：
   * 內建 Model Context Protocol (stdio 或 HTTP 埠號 8080)，供 AI Agent 原生調用瀏覽、點擊、輸入與多標籤頁狀態管理。

---

## 2. 環境檢測與快速執行

本環境已在 WSL2 Ubuntu 完成 Lightpanda `v1.0.2` 引擎配置，並提供跨平台 Python 整合控制器 [lightpanda_client.py](./scripts/lightpanda_client.py)。

### 2.1 檢查環境與 CDP 狀態
```powershell
python C:\Users\Anu\.gemini\config\skills\lightpanda-browser\scripts\lightpanda_client.py status
```

### 2.2 秒級抓取網頁並轉為 Markdown
```powershell
python C:\Users\Anu\.gemini\config\skills\lightpanda-browser\scripts\lightpanda_client.py fetch "https://news.ycombinator.com" --dump markdown --wait-ms 2000
```

### 2.3 提取結構化資料 (JSON-LD / Meta / Twitter Card)
```powershell
python C:\Users\Anu\.gemini\config\skills\lightpanda-browser\scripts\lightpanda_client.py fetch "https://example.com" --dump structured_data
```

### 2.4 指定 DOM 選擇器 (CSS Selector) 局部萃取
```powershell
python C:\Users\Anu\.gemini\config\skills\lightpanda-browser\scripts\lightpanda_client.py fetch "https://finance.yahoo.com/quote/AAPL" --selector "#quote-header-info" --dump markdown
```

---

## 3. CDP 伺服器啟動與 Playwright / Puppeteer 串接

當需要執行複雜的登入、多步驟點擊或即時截圖時，可啟動 CDP 伺服器模式：

### 3.1 啟動 CDP 伺服器 (背景守護或終端監聽)
```powershell
# 透過 Python Bridge 啟動
python C:\Users\Anu\.gemini\config\skills\lightpanda-browser\scripts\lightpanda_client.py serve --port 9222

# 或直接在 WSL 執行
wsl ~/.local/bin/lightpanda serve --host 0.0.0.0 --port 9222
```

### 3.2 Node.js (Puppeteer) 串接範例
```javascript
const puppeteer = require('puppeteer-core');

async function run() {
  const browser = await puppeteer.connect({
    browserURL: 'http://127.0.0.1:9222'
  });
  const page = await browser.newPage();
  await page.goto('https://goodinfo.tw/tw/ShowMarginChart.asp?STOCK_ID=2330');
  const title = await page.title();
  console.log('頁面標題:', title);
  await browser.close();
}
run();
```

### 3.3 Python (Playwright) 串接範例
```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    context = browser.contexts[0]
    page = context.new_page()
    page.goto("https://www.moneydj.com/funddj/yp/iQuoteFundCatFund.djhtm?A=2&B=1&C=47")
    content = page.content()
    print("頁面長度:", len(content))
    browser.close()
```

---

## 4. Python 程式庫直接引用 (API Usage)

在自訂金融量化分析腳本中，可直接匯入 Python Bridge 函式：

```python
from lightpanda_client import fetch_markdown, fetch_html, fetch_structured_data

# 抓取 JavaScript 渲染後的 Markdown 報告
markdown_text = fetch_markdown("https://example.com/financial-report", wait_ms=2000)

# 抓取目標選擇器內容
table_md = fetch_markdown("https://example.com/stock-table", selector="#main-table")

# 抓取結構化 JSON-LD
meta_data = fetch_structured_data("https://example.com/article")
print(meta_data.get("openGraph"))
```

---

## 5. 檔案結構 (Artifact Index)

* [SKILL.md](file:///C:/Users/Anu/.gemini/config/skills/lightpanda-browser/SKILL.md) — 技能規範與完整操作手冊
* [lightpanda_client.py](file:///C:/Users/Anu/.gemini/config/skills/lightpanda-browser/scripts/lightpanda_client.py) — 跨平台 CLI 調度器與 Python API
* [cdp_example.js](file:///C:/Users/Anu/.gemini/config/skills/lightpanda-browser/scripts/cdp_example.js) — Node.js CDP 連線與探測範例
