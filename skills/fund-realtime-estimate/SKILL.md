---
name: fund-realtime-estimate
description: 基金即時預估——從 MoneyDJ 抓指定台股基金的前 N 大成分股（名稱+比例），用 TWSE/TPEX 開放資料把名稱對到股票代號，再用 Fugle API 取即時股價，以「權重 × 個股漲跌幅」加總推估每檔基金今天的漲跌（附覆蓋率與放大值、加權指數對照），輸出 HTML 報表並發布成 Artifact 連結。Use when the user asks for 基金即時預估、基金即時淨值推估、今天基金漲多少、盤中基金預估漲跌、或要跑 fun_nav.py。
argument-hint: "[--funds CODE:簡稱,...] [--add CODE:簡稱,...] [--top-n 10]"
---

# 基金即時預估

改寫自使用者的 `D:\Users\leo_huang\_tmp\fun_nav.py`。

## 流程

1. **名稱對代號**：TWSE `t187ap03_L` + TPEX `mopsfin_t187ap03_O`（簡稱 → 代號，約 2000 支）。
2. **持股**：MoneyDJ `yp013000.djhtm?a={code}` 的持股表（`table.t01`，左右兩組 投資名稱/比例），取權重前 N 大（預設 10）。
3. **報價**：Fugle `stock.intraday.quote`，個股 + 加權指數 `IX0001`。
4. **推估**：
   - 推估漲跌 = Σ(權重 × 漲跌幅)，權重是佔基金的原始比例，不正規化（與原程式相同）。
   - 放大 = 推估 ÷ 覆蓋率，假設其餘持股與前 N 大同步（新增欄位，輔助參考）。
5. **輸出**：`report.html`（符合 artifact 規範、台股紅漲綠跌、深淺色）+ `summary.json`。

## 執行

Python：`D:\Obsidian\Claude_Use\.smc-env\Scripts\python.exe`（已有 requests、bs4、fugle-marketdata；
這台電腦的 `python` 是 MS Store 空殼）。別台電腦需 `pip install requests beautifulsoup4 fugle-marketdata`。

```bash
PYTHONIOENCODING=utf-8 "D:/Obsidian/Claude_Use/.smc-env/Scripts/python.exe" \
  "<skill>/scripts/fund_estimate.py" --out "<scratchpad>/fund_est/report.html"
```

| 參數 | 說明 |
|---|---|
| `--funds` | 只跑這些基金，取代 config 清單。格式 `ACDD04:台科,ACFH15:復華`，也可直接貼 MoneyDJ 網址（含 `a=代碼`）。 |
| `--add` | 在 config 清單之外再加幾檔。 |
| `--top-n` | 前幾大持股，預設 10（config.json）。 |
| `--config` | 預設 `<skill>/config.json`。 |

約 30 秒（8 檔基金、33 支股票）。進度印在 stderr，stdout 最後一行是摘要 JSON（各基金 est/scaled/covered、未對應名稱 `unresolved`）。

**預設基金清單在 `config.json`**（台科、大壩、奔騰、復華、鴻運、台運籌、路伯邁、元大；
`_disabled_funds` 是原程式註解掉的那幾檔）。使用者要長期增減基金就改這個檔；只是這次要看別檔就用 `--funds`/`--add`。

**Fugle API key** 依序讀：環境變數 `FUGLE_API_KEY` → skill 資料夾的 `fugle_api_key.txt`（`.gitignore` 排除，不上傳 GitHub）
→ `config.json` 的 `fugle_api_key`（repo 裡是空字串）。新電腦要自己建 `fugle_api_key.txt`（Fugle 開發者頁申請）。
**不要把 key 寫回 config.json**，這個 skill 放在公開 repo `delezue/skills`。

## 發布（輸出就是連結）

用 Artifact 發布 `report.html`（`icon: "chart"`）。同一個對話內再跑一次就用同一個檔案路徑重新發布，連結不變。
回覆：Artifact 連結 + 幾句重點（大盤漲跌、推估最高/最低的基金、各檔覆蓋率範圍、`unresolved` 若非空要列出）。

## 檢查

- `unresolved` 應為空。非空代表持股名稱沒對到代號，該檔持股不計入推估，報表代號欄顯示橘色「未對應」。
- `n_quotes` 應等於 `n_symbols`；少了就看 stderr 的取價失敗訊息（Fugle 額度或代號錯）。
- 非交易時段跑：Fugle 回傳最近一個交易日的收盤漲跌，報表標頭的「報價日期」會顯示是哪一天，回覆時要講清楚不是即時。

## 陷阱

1. **覆蓋率約 50–70%**（2026-10-16 實測 48.6%–72.2%），推估漲跌本質上是下界近似值；集中型基金（元大 ACYT162）覆蓋率較高。
2. **持股是 MoneyDJ 月報**（`資料月份`，例如 2026/09/30），不是當日實際部位，月中換股不會反映。
3. **名稱比對**：先完全比對，再去掉 `*`、`-KY` 尾巴比對，最後才用前綴比對並取最長簡稱。原程式的 `name in abbr or abbr in name`
   子字串比對會讓短簡稱誤配，已改掉。MoneyDJ 名稱會帶 `*`（如「國巨*」）。
4. **TPEX 憑證鏈缺中繼憑證**，該請求 `verify=False`（原程式就這樣，是對方網站問題）。
5. MoneyDJ 請求加 `&_=<時間戳>` 繞過伺服器端舊快取（同 `moneydj-fund-nav-high-report` 陷阱 0）。
6. 原程式報表是綠漲紅跌，已改成台股慣例紅漲綠跌。

## 驗證紀錄

2026-10-16 10:51 盤中：8 檔基金全部 10 檔持股、33/33 支對到代號（人工核對名稱對代號全對）、33/33 取到報價；
加權 +0.92%，各基金推估 +0.57%～+1.28%。

## 檔案

| 檔案 | 用途 |
|---|---|
| `scripts/fund_estimate.py` | 主程式（爬持股 → 對代號 → Fugle 報價 → 推估 → HTML + summary.json） |
| `config.json` | 預設基金清單、前 N 大、Fugle API key |
