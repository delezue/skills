# Antigravity Quant Skills Library (量化技能庫)

此倉庫專門存放 Google Antigravity (AGY) 量化交易與分析相關之專業 Skills。

## 📦 已收錄技能清單

### 1. [`skills/quant-iwy-lead`](skills/quant-iwy-lead/)
- **名稱**：IWY 美股巨頭領先指標量化系統 (ZLEMA-BBI 13/21/34/55)
- **標的**：^TWII (台股加權指數) / 台股正二 (00685L) / 美股 IWY
- **核心邏輯**：利用美股凌晨 04:00 收盤確定訊號與台股上午 09:00 開盤之間的 5 小時時間差，實現嚴格 100% 因果時序、零未來函數之 Open-to-Open 實盤操作。
- **實盤回測成效 (^TWII 2023-10-01 ~ 2026-10-08)**：
  - 累積總報酬：**+218.39%** (同期大盤死抱 +197.83%)
  - 超額報酬 (Alpha)：**+20.56%**
  - 勝率：**66.2%** (51勝 / 26負)
  - 盈虧比：**3.94**
  - 最大回撤：**-7.49%** (大盤最大回撤 -28.69%)

### 2. [`skills/quant-ehlers-reclaim`](skills/quant-ehlers-reclaim/)
- **名稱**：Adaptive Ehlers Percentile Reclaim (方案 B 1.0x 黃金參數純現貨階梯防守/停利量化系統)
- **標的**：^TWII (台股加權指數) / 0050 / 美股科技 (QQQ, SMH) / 權值股 (TSM)
- **核心技術**：台股黃金最佳參數（volLen=12, ehlersMom=12, pctLen=40, lowerMult=0.8, exitWeight=0.6）+ 波動率自適應 EMA + 非線性 Ehlers 動量距離濾波 (TrendMA) + 75% Nearest-Rank 動態通道 + 破底翻站回下軌進場 + 階梯式鎖利線 (0.6×TrendMA + 0.4×LowerBand)。
- **實盤回測成效 (^TWII 過去 3 年 2023-10-01 ~ 2026-10-08，純現貨零槓桿)**：
  - 累積總報酬：**+220.99%** (同期大盤死抱 +201.54%，超額報酬 Alpha **+19.45%**)
  - 最大回撤：**-13.55%** (大盤最大回撤 **-28.69%**，回撤深度大幅削減超過一半 -52.8%)
  - 卡瑪比率 (Calmar)：**16.30** (大盤 7.02，風險調整後績效為大盤的 2.3 倍 +132%)
  - 夏普比率 (Sharpe)：**2.36** (大盤 1.84)
  - 勝率：**57.9%** (11勝 / 8負)，獲利因子 (Profit Factor)：**8.12**，總交易僅 19 筆
- **全週期歷史跨期驗證 (^TWII 2023-01-01 ~ 2026-10-08)**：
  - 累積總報酬：**+266.44%** (大盤 +248.81%，零槓桿完勝大盤)
  - 最大回撤：**-13.55%**，卡瑪比率：**19.66** (大盤 8.67)

### 3. [`skills/barchart-gamma-exposure`](skills/barchart-gamma-exposure/)
- **名稱**：Barchart Gamma Exposure (GEX) 關鍵價位爬蟲
- **標的**：美股個股 / ETF（TSM、NVDA、SPY、QQQ…）
- **輸出**：日期、股價、漲跌幅、gamma flip point、put wall、call wall（文字或 `--json`）
- **技術**：Barchart 有 AWS WAF JavaScript challenge，一般 HTTP 只拿到 202 空頁 → 以 Node + Playwright Chromium headless 讀取渲染後頁面。
- **範例 (TSM, 10/12/26)**：股價 444.35 (-1.98%)、gamma flip 435.41、put wall 420.00、call wall 450.00

### 4. [`skills/fund-realtime-estimate`](skills/fund-realtime-estimate/)
- **名稱**：基金即時預估（台股基金盤中漲跌推估）
- **標的**：台股基金（預設台科、大壩、奔騰、復華、鴻運、台運籌、路伯邁、元大，清單在 `config.json`）
- **流程**：MoneyDJ 前 10 大持股（名稱+比例）→ TWSE/TPEX 開放資料名稱對代號 → Fugle 即時報價 → Σ(權重 × 漲跌幅) 推估基金漲跌，附覆蓋率、放大值（推估 ÷ 覆蓋率）與加權指數對照，輸出 HTML 報表（台股紅漲綠跌）。
- **需求**：`pip install requests beautifulsoup4 fugle-marketdata`，Fugle API key 放環境變數 `FUGLE_API_KEY` 或 skill 資料夾的 `fugle_api_key.txt`（已 gitignore）。
- **範例 (2026-10-16 11:00 盤中)**：加權 +0.68%；奔騰 +0.96%、復華 +0.94%、元大 +0.09%；前 10 大覆蓋率 48.6%～72.2%。

### 5. [`skills/cnyes-fund-zlema-viewer`](skills/cnyes-fund-zlema-viewer/)
- **名稱**：鉅亨基金 ZLEMA 看盤工具（含相對加權指數強弱）
- **輸入**：鉅亨基金代號（`A36004`、`A1rqsDL`）或 fund.cnyes.com 基金網址
- **資料**：anuefund NavHIS 一次抓成立以來全部淨值 → 本地 SQLite，之後只用 cnyes 分頁 API 補最新；自動對應 cnyes 代號與 anue FundID；去掉早期逐日曆天補值的假日資料。
- **指標**：ZLEMA 13/21/55/200（SMA 起始，與 TradingView / pandas_ta 驗算一致）、距今年高點、ZLEMA13 乖離（歷史 P5/P95）、相對加權指數強弱（基金含息總報酬 vs 證交所發行量加權股價報酬指數 2020 年起；20/60/120/250 日超額報酬、Mansfield RS、60 日 β）。
- **輸出**：ECharts 五層同步互動看盤 HTML（區間切換、均線開關、游標讀值、深淺色、台股紅漲綠跌）。
- **需求**：`pip install requests`；本地資料庫 `data/fund_nav.db` 不上傳，第一次執行自動建立（大盤含息指數約 1 分鐘，之後每次數秒）。
- **範例 (A36004 安聯台灣科技，2026-10-15)**：淨值 781.99（-6.60%）、距今年高點 -11.20%、ZLEMA13 乖離 -6.18%、相對大盤 250 日 +92.4pp、Mansfield RS +8.3%、β60 1.50。

### 6. [`skills/goodinfo-margin-maintenance`](skills/goodinfo-margin-maintenance/)
- **名稱**：Goodinfo 個股融資維持率與斷頭追繳點位精算終端
- **標的**：任意台股上市櫃個股（如 `2330`、`2317`、`2454`、`2308`、`2382`）
- **核心技術**：透過 Playwright Chrome 引擎繞過 Cloudflare 防護自動爬取 `goodinfo.tw/tw/ShowMarginChart.asp` 信用交易日統計（`#tblDetail`），依台灣證交所 60% 融資成數（初始維持率 `166.67%`）精算四大機構級融資成本線與融資維持率模型：
  1. **WAC 動態存量池法**（每日賣出與現償等比例沖銷，買進按收盤價滾入）
  2. **FIFO 先進先出周轉池法**（由最新日逆向回溯累加融資買進張數至湊滿當日融資餘額）
  3. **20D Rolling 近 20 日短線追高批次成本**
  4. **Anchored AVWAP 區間總買進均價**
- **輸出**：推算個股 **`140%` 警戒價** 與 **`130%` 法定斷頭價**，並產出通過 `node --check` 驗證之深色機構級三窗格互動式 ECharts HTML 看盤報表。

### 7. [`skills/twse-market-margin-wac`](skills/twse-market-margin-wac/)
- **名稱**：TWSE 全上市股票 (`CFICode=ESVUFR`) 與 32 大產業別 WAC 融資維持率全景監測終端
- **標的**：全台灣證券交易所上市普通股（`CFICode = ESVUFR`，共約 1,087 檔、橫跨 32 大產業別）
- **核心技術**：
  1. 自動爬取 `isin.twse.com.tw/isin/C_public.jsp?strMode=2` 篩選 `CFICode = ESVUFR`（有價證券代號及名稱、產業別）。
  2. 批次串接 TWSE 官方全市場信用交易日統計 (`MI_MARGN`) 與每日收盤行情 (`MI_INDEX`)，內建增量日快取引擎（本地 `cache/` 已 gitignore）。
  3. 套用 `goodinfo-margin-maintenance` 之 **WAC 動態存量池演算法（含除權息/拆股/減資自動因子校正）**，精算全市場 1,087 檔個股之 WAC 融資維持率 (%)、140% 警戒價、130% 斷頭價，以及 **32 大上市產業別之加權 WAC 維持率 (%) 與等權平均維持率 (%)**。
- **輸出**：深色機構級互動式 ECharts HTML 全景監測報表（含 32 產業橫向排行、60 日產業 vs 全市場維持率趨勢、產業內個股融資市值 × 維持率散佈圖與全市場即時篩選表）。

---
*Created by [delezue](https://github.com/delezue)*
