# moneydj-fund-nav-high-report

Claude Code skill：爬 MoneyDJ 基金分類頁的報酬表，進入每檔基金頁抓 淨值日期／最新淨值／最高淨值(年)，
計算「最新淨值與最高淨值差距 %」，輸出財金基金比較 HTML 報表與 CSV。

## 移植到另一台電腦

需要：**Claude Code** 和 **Python 3.8 以上**（只用標準函式庫，不用 pip 裝任何套件）。

1. 把 `moneydj-fund-nav-high-report.zip` 複製到新電腦，解壓縮到任何地方。
2. 進入解壓出來的 `moneydj-fund-nav-high-report` 資料夾：
   - **Windows**：雙擊 `install.bat`
   - **macOS / Linux**：`bash install.sh`
3. 安裝程式會：
   - 複製到 `~/.claude/skills/moneydj-fund-nav-high-report`（Windows 是 `%USERPROFILE%\.claude\skills\...`）
   - 找到 Python 3.8+，把路徑寫進 `python_path.txt`
   - 試跑 3 檔基金，確認網路和 MoneyDJ 都正常
4. 重新開啟 Claude Code，輸入 `/moneydj-fund-nav-high-report`，或直接貼 MoneyDJ 分類網址請它產生報表。

沒有 Python：到 https://www.python.org/downloads/ 下載安裝，Windows 安裝時勾選 **Add python.exe to PATH**，再執行一次 `install.bat`。

也可以不跑安裝程式：直接把資料夾放到 `~/.claude/skills/` 底下即可，Claude 會依 SKILL.md 自己找 Python。

## 手動執行（不透過 Claude）

```bash
python scripts/fund_nav_high_report.py --category 47 --out report/report.html
```

`--category` 是分類頁網址的 `C=` 值（47 = 台灣）。其他參數見 `SKILL.md`。

## 資料驗證（選用）

`scripts/verify/` 用真實瀏覽器核對爬回來的資料，需要 **Node.js** 和 **Playwright**：

```bash
npm i -g playwright
npx playwright install chromium
```

在 `funds.csv` 所在資料夾執行 `node <skill>/scripts/verify/browser_check.js 60`，再執行 `python <skill>/scripts/verify/compare.py`。
若 Playwright 裝在別處，設定環境變數 `PLAYWRIGHT_PATH` 指到它的 `node_modules/playwright`。

## 內容

| 檔案 | 用途 |
|---|---|
| `SKILL.md` | Claude 讀的說明：步驟、參數、已知資料陷阱、驗證結果、修改紀錄 |
| `scripts/fund_nav_high_report.py` | 爬蟲與報表產生程式 |
| `templates/report_template.html` | 報表範本 |
| `scripts/verify/` | 選用的資料驗證腳本 |
| `install.bat` / `install.sh` | 安裝程式 |
