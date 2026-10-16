---
name: cnyes-fund-zlema-viewer
description: 輸入鉅亨網基金代號（如 A36004）或 fund.cnyes.com 基金網址，爬取成立以來每日歷史淨值（日期、淨值、漲跌幅）存入本地 SQLite（第二次起先讀本地、只補抓最新），計算 ZLEMA(13/21/55/200)、距今年以來最高淨值的漲跌幅、與 ZLEMA(13) 的乖離率，產生專業看盤 HTML 互動工具（四層同步圖、區間切換、均線開關、游標讀值、深淺色）並發布成 Artifact 連結。Use when the user asks for 基金歷史淨值看盤、基金 ZLEMA、基金距今年高點、基金乖離率、鉅亨基金淨值 SQLite、or gives a cnyes fund code/URL and wants an interactive chart.
argument-hint: "<基金代號或鉅亨網址> [--full]"
---

# 鉅亨基金 ZLEMA 看盤工具

## 做什麼

1. **歷史淨值**：日期、淨值、漲跌（點數）、漲跌幅 %，從成立日起。
2. **SQLite**：`<skill>/data/fund_nav.db`，表 `nav(code,date,nav,change,change_pct,source)` 與 `fund_info`。
   第一次整段下載；之後先讀本地，從 cnyes 最新頁往回翻到本地最後一天為止，只補新的，並核對最後一天的淨值是否一致。
3. **指標**（Python 算好嵌入 HTML）：
   - `ZLEMA(n) = EMA_n(2·x_t − x_{t−lag})`，`lag = (n−1)//2`，α = 2/(n+1)，n = 13/21/55/200。EMA 以前 n 個 src 的 SMA 起始，第一個值在第 lag+n−1 根（ZLEMA200 從第 298 根起）。
   - 距今年高點 % = 淨值 ÷（當年 1/1 起至當日的最高淨值）− 1，每年 1 月重置。
   - ZLEMA13 乖離 % = 淨值 ÷ ZLEMA13 − 1；圖上虛線是全部歷史乖離率的 P5／P95。
4. **相對強弱（vs 加權指數）**（`scripts/relative_strength.py`）：
   - 大盤 = 證交所「發行量加權股價報酬指數」（含息），API `https://www.twse.com.tw/rwd/zh/TAIEX/MFI94U?date=YYYYMM01&response=json`，
     一次一個月、民國日期。**使用者指定只抓 2020-01-01 起**（`TRI_START`，證交所最早 2003-01），表 `bench_tri`，所有基金共用；
     第一次約 82 個月 52 秒，之後每次只重抓最近兩個月。起始日前的舊資料會被刪掉。
   - 基金 = 含息總報酬：配息級別用 anue `DividendHIS`（表 `dividend`）在除息日以當日淨值再投入；累積型等於淨值。
     不用 ^TWII（不含息，每年少 3–4 個百分點，會讓基金看起來偏強）。
   - 指標：20/60/120/250 日超額報酬（含息報酬差，pp）、Mansfield RS = RS ÷ 其 250 日均線 − 1、60 日 β、RS 是否 52 週新高；
     圖的第 5 層是「相對加權」線，以目前顯示區間的第一天 = 100（切換區間或縮放時 JS 重新定基）。
   - 2026-10-16 用獨立 pandas 腳本驗算 3 檔：超額報酬、MRS、β 全部一致。`--no-rs` 可跳過（不連證交所）。
5. **HTML**：KPI 列（距今年高點、乖離、今年報酬、站上幾條 ZLEMA、四條 ZLEMA 數值）→ 區間鈕（1M…全部，預設 1Y）
   → ZLEMA 開關 → 游標讀值列 → ECharts 四層同步圖（淨值+ZLEMA／日漲跌／距今年高點／乖離）+ 底部縮放軸。台股紅漲綠跌、深淺色。

## 執行

Python：`D:\Obsidian\Claude_Use\.smc-env\Scripts\python.exe`（只需 `requests`；驗算才用 pandas）。設 `PYTHONIOENCODING=utf-8`。

```bash
PYTHONIOENCODING=utf-8 "D:/Obsidian/Claude_Use/.smc-env/Scripts/python.exe" \
  "<skill>/scripts/fund_zlema_viewer.py" A36004 --out "<scratchpad>/fund_A36004/A36004.html"
```

| 參數 | 說明 |
|---|---|
| `fund` | 代號（一個英文字母 + 5 位數字）或鉅亨網址（取末段代號）。 |
| `--out` | HTML 路徑。 |
| `--full` | 忽略本地資料整段重抓（懷疑本地資料有誤時用）。 |
| `--db` | 預設 `<skill>/data/fund_nav.db`。 |

整段下載約 2 秒。stdout 最後一行是摘要 JSON：最新淨值、漲跌幅、年高、距年高、乖離、四條 ZLEMA、`sync`（mode=full/incremental、added 新增筆數、check 本地最後一天 vs 網站）。

## 發布

用 Artifact 發布 HTML（`icon: "chart"`，範本已符合 artifact 規範：無 doctype、顏色 token、深淺色）。同一對話再跑同一檔基金就用同一路徑重新發布。
回覆：連結 + 最新淨值與漲跌、距今年高點、乖離率（和 P5/P95 比較）、站上幾條 ZLEMA、本次新增幾筆。

## 資料來源與陷阱（2026-10-16 實測）

1. **完整歷史**：`https://www.anuefund.com/anuefundApi/FundDetail/FundInfo?fundDetailEnum=NavHIS&FundID={code}`，
   一次回傳成立以來全部（A36004：6498 筆，2001-04-03 起），免認證。`data.navHIS[]` 欄位 `navDate/nav/upDown/upDownRate`，
   基本資料在 `data.hearder`（**API 自己拼錯，不是 header**）。`upDownRate` 只到小數 2 位。
2. **增量**：`https://fund.api.cnyes.com/fund/api/v1/funds/{code}/nav?format=table&page=N`，每頁固定 10 筆（`limit`/`per_page` 無效），
   新到舊，`tradeDate` 是 Unix 秒（用台灣時區轉日期），`changePercent` 小數 5 位。這個 API 只有約 3659 筆（2011 年起），所以完整歷史用 anue。
   既有 `fund-nav` skill 用的是這個分頁 API 從頭翻（366 頁），慢且不完整。
3. 斷層超過 60 頁（約 600 個交易日）才會改用 anue 整段補，正常不會發生。
4. 兩個來源淨值一致：缺 22 筆後補抓 0 差異；cnyes 第 120 頁（2021-11）抽 10 筆與 anue 0 差異。
5. **ZLEMA 驗證（2026-10-16）**：與 TradingView Pine 寫法、pandas_ta 式（SMA 起始）在 3 檔基金的最新值到小數 4 位相同；
   與獨立 pandas 版本逐根差 ≤ 0.00005。斜坡 x=t 測試：ZLEMA 13/21/55 延遲 0 根（EMA 為 6/10/27 根）；
   ZLEMA200 延遲 0.5 根，因為 (200−1)/2 = 99.5 取整為 99，與 Pine / pandas_ta 相同，屬於定義本身。
   舊版用 x[0] 起始且 t<lag 時把 src 當 x，最新值不受影響，但最早一段 ZLEMA200 偏差可達 37%（約 1000 根後才收斂），已改掉。
7. **anue 早期資料逐日曆天補值**（2026-10-16 A32007 野村鴻運發現）：1990–2014 每年 365 筆，週末／假日是前一天淨值的複本，
   2015 起才是交易日（約 245 筆）。`trading_rows()` 在「該年超過 300 筆」的年份去掉週末列和淨值未變且漲跌 0 的列後才算指標
   （A32007：12019 → 8812 筆）；資料庫保留原始資料。摘要 JSON 的 `sync.filled_dropped` 是去掉的筆數。
8. **來源漲跌幅偶爾和淨值對不上**（A32007 2024-03-18 標 0%，淨值實際 +1.73%）：和淨值重算差超過 0.05 個百分點就用重算值。
9. 早年單日 ±10% 左右的跌幅多在 2 月（1994、1995、1996、1999），可能是配息除息，淨值本身與來源一致，不做調整。
10. **鉅亨有兩套代號**（2026-10-16 `A1rqsDL` 發現）：fund.cnyes.com 網址末段是 cnyes 代號（可能有大小寫，如 `A1rqsDL`，
    **不能轉大寫**），anue NavHIS 要用 anue FundID（`A49015`）。國內基金多半兩者相同（A36004、A32007）。
    `resolve_ids()` 查 `fund.api.cnyes.com/fund/api/v1/funds/{code}`，從 `forSaleUrl` 的 `FundID=` 取 anue 代號；
    cnyes 查不到（404）就把輸入當 anue FundID，增量也改用 anue 整包過濾。資料庫以使用者輸入的代號為 key。
    使用者可能把引數連 `<>` 一起貼進來（`<A1rqsDL>`），`parse_code()` 會去掉。
11. **配息級別**（月配 T 級別等）：淨值在除息日下跌，看盤工具用的是淨值，不是含息總報酬，所以距今年高點會被配息放大。
    配息紀錄：anue `fundDetailEnum=DividendHIS`（`excludingDate`、`totalDistribution`）。回覆時要提醒，必要時算含息的距高點。
6. 範本 JS 的區間值：`RANGES` 第二欄（月數/'ytd'/'all'）才是 `startIdx` 的參數，`range` 變數存的是按鈕標籤，用 `RMAP[range]` 轉。
   曾經把標籤和值混用造成 `Invalid time value`。

## 檔案

| 檔案 | 用途 |
|---|---|
| `scripts/fund_zlema_viewer.py` | 爬蟲（anue 全量 / cnyes 增量）→ SQLite → 指標 → 填範本 |
| `templates/viewer_template.html` | 看盤範本，`{{TITLE}}`、`{{DATA_JSON}}` 由腳本填入，ECharts 5.4.3（cdnjs） |
| `data/fund_nav.db` | 本地淨值資料庫（多檔基金共用） |
