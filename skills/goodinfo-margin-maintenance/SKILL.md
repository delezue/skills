---
name: goodinfo-margin-maintenance
description: >-
  透過瀏覽器引擎自動爬取 Goodinfo! 台灣股市資訊網 (ShowMarginChart.asp) 之任意台股個股信用交易（融資融券）日統計資料，
  依華爾街機構量化法與台灣證交所信用交易規則（60% 融資成數，初始維持率 166.67%），精算四大融資成本線與融資維持率模型
  （WAC 動態存量池、FIFO 先進先出周轉池、近20日追高批次、區間錨定 AVWAP），並推算 140% 警戒價與 130% 追繳斷頭價，
  輸出通過 node --check 驗證之深色機構級三窗格互動式 ECharts HTML 看盤報表。當使用者要求查詢或計算台股個股「融資維持率」、
  「融資成本線」、「斷頭價 / 追繳價」或提供 Goodinfo ShowMarginChart 網址時自動觸發。
---

# Goodinfo 個股融資維持率與斷頭追繳點位精算終端 (`goodinfo-margin-maintenance`)

本技能可針對任意台股代號（如 `2330`、`2317`、`2454`、`2308`、`2382` 等），自動繞過 Goodinfo Cloudflare 防護爬取 `ShowMarginChart.asp?STOCK_ID=<代號>&CHT_CAT=DATE` 之完整信用交易日統計表（`#tblDetail`），計算四大機構級融資成本線與融資維持率模型，並產出互動式三窗格 ECharts HTML 看盤軟體。

---

## 核心演算法與台灣證交所法規基準

1. **法定融資成數（LTV）**：
   * 台股上市櫃股票預設融資成數為 **`60%`**（散戶自備保證金 `40%`，向券商借貸 `60%`）。
   * 買進當日之**初始融資維持率（損益兩平線）**恆為：
     $$\text{初始維持率} = \frac{1}{0.60} = \mathbf{166.67\%}$$
2. **第 $t$ 日融資維持率精算公式**：
   $$M_t = \frac{P_t}{0.60 \times C_t} \times 100\% = 166.67\% \times \frac{P_t}{C_t}$$
3. **四大融資建倉成本 ($C_t$) 模型**：
   * **模型 A（WAC 動態存量池法）**：券商與 CMoney 標準存量加權平均成本法，每日賣出與現償 (`Sell + Repay`) 按前一日池中均價等比例沖銷，新買進 (`Buy`) 按當日收盤價計入池中。
   * **模型 B（FIFO 先進先出周轉池法）**：由第 $t$ 日逆向回溯累加每日 `融資買進(張)` 直到湊滿當日 `融資餘額(張)`，精確反映目前留在場內的最新換手籌碼成本。
   * **模型 C（20D Rolling 短線追高批次）**：計算近 20 個交易日融資買進加權均價與維持率，捕捉高檔追價散戶的套牢壓力。
   * **模型 D（Anchored AVWAP 區間總買進均價）**：全區間累計買進加權平均成本。
4. **三大關鍵維持率門檻與對應股價**：
   * **`166.67%` 損益兩平價**：$1.00 \times C_t$
   * **`140.00%` 追繳警戒價**：$0.60 \times 1.40 \times C_t = \mathbf{0.84 \times C_t}$（自成本下跌 `-16%`）
   * **`130.00%` 法定斷頭價**：$0.60 \times 1.30 \times C_t = \mathbf{0.78 \times C_t}$（自成本下跌 `-22%`，$T+2$ 強制平倉）

---

## 執行步驟 (Workflow Execution)

當使用者要求計算某檔台股的融資維持率或提供 Goodinfo 信用交易網址時，直接執行內建腳本 [goodinfo_margin_analyzer.py](./scripts/goodinfo_margin_analyzer.py)：

### 指令格式

```powershell
python "C:\Users\Anu\.gemini\config\skills\goodinfo-margin-maintenance\scripts\goodinfo_margin_analyzer.py" --stock-id 2330 --output "D:\Python\_tmp\Goodinfo_2330_Margin_Maintenance_Report.html" --backup "C:\Users\Anu\orca\projects\stock\Goodinfo_2330_Margin_Maintenance_Report.html"
```

### 參數說明
* `--stock-id`：（必填）台股代號，例如 `2330`、`2317`、`2454`。
* `--ltv`：（選填）融資借貸成數，預設為 `0.60`（即 60%）。
* `--output`：（必填）主要輸出之 HTML 報表絕對路徑（如 `D:\Python\_tmp\Goodinfo_<代號>_Margin_Report.html`）。
* `--backup`：（選填）同步備份之第二輸出路徑（如工作區 `C:\Users\Anu\orca\projects\stock\Goodinfo_<代號>_Margin_Report.html`）。

### 品質檢驗與回覆規範
1. 腳本內部已自動整合 **雙 CDN 備援（Cloudflare `cdnjs` + `jsDelivr`）** 與 **`node --check` JavaScript 語法檢查**。
2. 執行完成後，根據終端機輸出的 JSON/表格摘要，站在**華爾街機構基金經理人**視角向使用者報告：
   * 最新收盤價、融資餘額張數、近 10 日融資增減趨勢；
   * WAC 存量池、FIFO 周轉池與近 20 日批次之最新**融資成本線**與**融資維持率 (%)**；
   * 對應之 **`140%` 警戒價** 與 **`130%` 斷頭追繳價**；
   * 附上可點擊的 `[報表檔名](file:///...)` 連結。
