---
name: twse-market-margin-wac
description: >-
  自動爬取台灣證券交易所本國上市證券國際證券辨識號碼一覽表 (isin.twse.com.tw/isin/C_public.jsp?strMode=2)，
  篩選 CFICode = ESVUFR（全體上市普通股約 1,087 檔與 32 大產業別），串接 TWSE 官方全市場信用交易日統計 (MI_MARGN)
  與每日收盤行情 (MI_INDEX)，依華爾街機構量化法與 goodinfo-margin-maintenance 之 WAC 動態存量池演算法（含除權息/拆股/減資自動因子校正），
  精算：(1) 全體上市有價證券代號的 WAC 融資維持率 (%)、140% 警戒價、130% 斷頭價，以及 (2) 32 大上市產業別的加權/等權 WAC 融資維持率 (%)，
  並輸出通過 node --check 驗證之深色機構級互動式 ECharts HTML 全景監測報表。當使用者要求計算「全上市股票融資維持率」、
  「產業別融資維持率」、「全市場斷頭/追繳名單」或提供 isin.twse.com.tw (CFICode=ESVUFR) 網址時自動觸發。
---

# TWSE 全上市股票 (`CFICode=ESVUFR`) 與 32 大產業別 WAC 融資維持率全景監測終端 (`twse-market-margin-wac`)

本技能可一次性針對**全台灣證券交易所上市普通股（`CFICode = ESVUFR`，共約 1,087 檔、橫跨 32 個產業別）**，自動爬取最新上市證券清單與近 60 個交易日（一完整季度）之全市場信用交易日統計與收盤價，精算每一檔上市股票與每一個產業別的 **WAC 動態存量池融資維持率 (%)**，並產出具備三窗格互動圖表（32 產業橫向排行、60 日產業維持率趨勢、產業內個股融資市值 × 維持率散佈圖）與全市場搜尋篩選表格的專業 HTML 報表。

---

## 核心方法論與演算法架構

1. **上市標的與產業別自動對映 (`isin.twse.com.tw`)**：
   * 自動抓取 `https://isin.twse.com.tw/isin/C_public.jsp?strMode=2`（`cp950` 編碼），精確篩選 **`CFICode == 'ESVUFR'`** 之上市普通股，擷取 `有價證券代號及名稱` 與 `產業別`（共 32 大類）。
2. **全市場日級信用交易與行情批次引擎 (`MI_MARGN` + `MI_INDEX`)**：
   * 透過 `curl_cffi` 批次抓取近 `--days`（預設 60 個有效交易日）之 TWSE 官方全市場融資買進、融資賣出、現金償還、前日餘額、今日餘額與收盤價，並內建本地磁碟快取機制（已抓過的歷史交易日毫秒級讀取，僅增量抓取最新交易日）。
3. **個股 WAC 動態存量池模型（含除權息/拆股/減資自動校正）**：
   * 法定融資成數預設 `LTV = 0.60`（初始維持率 $1 / 0.60 = 166.67\%$）。
   * 每日融資賣出與現償 (`Sell + Repay`) 按前一日池中均價等比例沖銷，新買進 (`Buy`) 按當日收盤價計入：
     $$C_t^{\text{WAC}} = \frac{\max(0, B_{t-1} - (\text{Sell}_t + \text{Repay}_t)) \cdot C_{t-1}^{\text{WAC}} + \text{Buy}_t \cdot P_t}{\max(0, B_{t-1} - (\text{Sell}_t + \text{Repay}_t)) + \text{Buy}_t}$$
   * **除權息/拆股/減資防護**：當單日股價變動幅度超過台股漲跌幅限制（`> 14.5%`）時，自動依價格比例調整存量池基準成本，消除股票分割（如 1 拆 10 / 1 拆 20）或減資換股造成的維持率失真。
   * **個股 WAC 融資維持率 (%)**：
     $$M_{i,t}^{\text{WAC}} = \frac{P_{i,t}}{0.60 \times C_{i,t}^{\text{WAC}}} \times 100\%$$
4. **32 大產業別雙軌維持率指標**：
   * **產業加權 WAC 維持率 (%)**：以該產業內所有具融資個股之「總融資擔保品市值」除以「總融資借貸金額（60% 成數）」，真實反映該產業整體融資資金池的水位：
     $$M_{\text{Industry}, t}^{\text{Weighted}} = \frac{\sum_{i \in \text{Ind}} (B_{i,t} \times 1000 \times P_{i,t})}{\sum_{i \in \text{Ind}} (B_{i,t} \times 1000 \times 0.60 \times C_{i,t}^{\text{WAC}})} \times 100\%$$
   * **產業等權平均維持率 (%)**：該產業內所有具融資餘額成分股之算術平均維持率，反映中小型股的普遍體感。

---

## 執行步驟 (Workflow Execution)

當使用者要求計算全市場上市股票或 32 大產業別的融資維持率時，直接執行內建腳本 [twse_market_margin_wac.py](./scripts/twse_market_margin_wac.py)：

### 指令格式

```powershell
python "C:\Users\Anu\.gemini\config\skills\twse-market-margin-wac\scripts\twse_market_margin_wac.py" --cfi ESVUFR --days 60 --output "D:\Python\_tmp\TWSE_ESVUFR_Market_Industry_WAC_Report.html" --backup "C:\Users\Anu\orca\projects\stock\TWSE_ESVUFR_Market_Industry_WAC_Report.html"
```

### 參數說明
* `--cfi`：（選填）篩選之 CFICode，預設為 `ESVUFR`（上市普通股）。
* `--days`：（選填）回溯滾動計算之有效交易日數，預設為 `60`（約一季）。
* `--ltv`：（選填）法定融資成數，預設為 `0.60`（60%）。
* `--output`：（必填）主要輸出之 HTML 報表絕對路徑（如 `D:\Python\_tmp\TWSE_ESVUFR_Market_Industry_WAC_Report.html`）。
* `--backup`：（選填）同步備份之第二輸出路徑（如工作區 `C:\Users\Anu\orca\projects\stock\TWSE_ESVUFR_Market_Industry_WAC_Report.html`）。
* `--cache-dir`：（選填）TWSE 歷史日資料快取目錄，預設存放於技能目錄下的 `cache/`，可大幅加速重複執行速度。

### 品質檢驗與回覆規範
1. 腳本內部已自動整合 **雙 CDN 備援（Cloudflare `cdnjs` + `jsDelivr`）** 與 **`node --check` JavaScript 語法檢查**。
2. 執行完成後，站在**華爾街機構基金經理人**視角向使用者報告：
   * 全市場上市股整體加權 WAC 維持率 (%)、總融資市值（億元）與獲利/套牢/警戒/斷頭家數結構；
   * 32 大產業別 WAC 維持率排行（指出最弱勢套牢產業與最強勢獲利避風港產業）；
   * 已跌破 `130%` 斷頭線與 `140%` 追繳警戒線之高危個股清單；
   * 附上可點擊的 `[報表檔名](file:///...)` 連結。
