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

---
*Created by [delezue](https://github.com/delezue)*
