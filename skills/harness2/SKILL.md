---
name: harness2
description: >
  基於 Google Research 官方開源之 Harness² 框架 (https://github.com/google-research/harness2,
  arXiv:2610.14224 "Harness²: Recursive Agent Harnessing for an Open World")。
  提供在不改變模型權重 (Fixed Model Weights) 與無須真實標籤回饋 (Label-Free / Rubric-Free) 下，
  針對 AI Agent 外圍八大組件 (System Prompt、Guardrails、Memory、Tool Guidance、Subagents、Skills、Scripts、Plugins)
  進行雙層遞迴優化：(1) 任務層級遞迴 (Task-Level Recursion: Propose–Probe–Compose 對比式探索，支援 Parallel 廣度與 Sequential 深度模式)，
  以及 (2) 駕馭層級遞迴 (Harnessing-Level Recursion: 跨任務經驗反思 Experience Reflection 與領域知識庫累積)。
  當使用者提及「harness2」、「Harness²」、「Recursive Agent Harnessing」、「Propose-Probe-Compose」或要求自動演化/優化 Agent Skill 與量化腳本時自動觸發。
---

# Harness² (`google-research/harness2`) — 開放世界雙層遞迴 Agent 駕馭與自動演化框架技能

本技能完整蒸餾並封裝 Google Research 發表之 **[Harness²: Recursive Agent Harnessing for an Open World](https://github.com/google-research/harness2)**（論文：`arXiv:2610.14224`），並提供可直接於本地端（含 Windows / Linux / Python 3.12~3.14）運行的確定性雙層遞迴演化引擎與量化策略自動調優適配器 (`BenchmarkAdapter`)。

---

## 一、核心理論與雙層遞迴架構 (Core Paradigm & Two-Level Recursion)

### 1. 什麼是 Harness 與 Harnessing？
* **Harness（代理裝備/外骨骼）**：圍繞在固定權重大型語言模型 (LLM) 外圍，使其能作為自主 Agent 解決複雜任務的完整系統，由 **8 大可編輯組件 (`c1..c8` Editable Surface)** 構成：
  1. **`systemprompt.md` (System Prompt)**：核心角色定義與頂層任務流程。
  2. **`guardrails.md` (Guardrails)**：安全邊界、不可違反之硬性約束與驗證檢查。
  3. **`LongTermMEMORY.md` (Memory)**：跨任務持久化記憶與領域知識。
  4. **`tool_descriptions/tool_guidance.md` (Tool Guidance)**：工具調用時機與參數最佳實踐。
  5. **`sub_agents/` (Subagents)**：子代理分工與委派定義。
  6. **`skills/*/SKILL.md` (Skills)**：模組化專業技能包（支援 `autotrigger` 自動觸發）。
  7. **`scripts/*.py` (Scripts)**：決定性可執行運算腳本與驗證工具。
  8. **`plugin/` (Plugins)**：工具迴圈中介軟體 (Middleware) 與攔截器。
* **Harnessing（遞迴駕馭）**：在不微調模型權重的前提下，透過觀察 Agent 執行軌跡 (`[ACTION] / [OBSERVATION] / [ERROR]`) 與產出物 (`Deliverables`) 的行為對比，自動修改並演化上述 8 大組件的過程。

---

### 2. 第一層：任務層級遞迴 (Task-Level Recursion: Contrastive `Propose–Probe–Compose`)
針對當前單一未知任務（無 Ground-Truth 標準答案或評分 Rubric），執行每次預算為 $k$（共 `4k` 次執行 Rollouts 與 `3k` 個改進階段）的三步閉環：
1. **Base Rollouts**：先以當前基準 Harness 執行 $k$ 次基準測試，收集基準軌跡與產出物。
2. **Propose（雙維度提案）**：
   - **通用不變提案 (`inv1..inv_k`, Invariant Edits)**：針對跨領域通用的執行缺陷（如未驗證邊界條件、格式遺漏、算術錯誤）提出修改。
   - **領域專屬提案 (`dom1..dom_k`, Domain-Specific Edits)**：結合領域經驗庫 (`Library`) 針對特定專業領域（如量化金融、法律、會計、軟體工程）提出修改。
3. **Probe（同任務探針驗證）**：將提案修改後的候選 Harness 實際在**同一任務**上執行，觀察修改前後的行為差異（Behavioral Contrast）。
4. **Compose & Select（對比合成與擇優）**：
   - 綜合所有候選探針的執行軌跡與產出物，合成出 $k$ 個最終強化版 Harness (`comp1..comp_k`)，並由 Selector 選出最佳版本。
   - **兩種擴展模式**：
     - **`--mode parallel` (平行遞迴 — 廣度探索)**：同時探索 $k$ 個通用與 $k$ 個領域候選者，再從共享證據池合成 $k$ 個組合。
     - **`--mode sequential` (序列遞迴 — 深度精煉)**：將每一步合成出的最佳 Harness 與累積證據傳遞至下一步，連續進行 $k$ 輪 `Propose–Probe–Compose` 深度迭代。

---

### 3. 第二層：駕馭層級遞迴 (Harnessing-Level Recursion: Experience Reflection)
當單一任務完成並選出採納版 Harness (`Adopted Harness`) 後：
* **經驗反思器 (Experience Reflector)** 會比對 `base_harness` 與 `adopted_harness` 的差異，以及探針執行前後的觀察結果，提煉出結構化的經驗條目寫入持久化的 **領域知識庫 (`Per-Domain Library`)**：
  ```xml
  <edits>
  component: scripts/summarize.py
  candidates: inv1
  change: 修正簽名金額加總邏輯，移除僅加總正數的過濾條件
  observed: 探針執行結果成功涵蓋了原本遺漏的貸方負向金額
  verdict: helped
  </edits>

  <experience>
  cue: 當對帳單或交易分類帳同時包含借方與貸方正負金額時
  lesson: 在加總腳本中必須保留正負號進行精確 Decimal 淨額結算，不可過濾負值。
  evidence: 移除 > 0 過濾後，產出總額與原始分類帳完全吻合。
  confidence: high
  </experience>
  ```
* 後續同領域的新任務會自動讀取此經驗庫與採納版 Harness，實現「越做越聰明」的終身學習！

---

## 二、CLI 指令與環境操作指南

本環境已安裝 `harness2` 套件（包含 7 個官方 CLI 入口點）：

| CLI 指令 | 用途說明 |
| :--- | :--- |
| `harness2-demo` | **無須 API Key 的本地確定性雙層遞迴示範**：真實執行 Python 腳本修改、Parallel 與 Sequential 兩種遞迴模式及經驗庫累積 |
| `harness2` | 主執行器：對指定 Benchmark (`--bench lab\|jb\|wb`) 執行 `--k K --mode parallel\|sequential` 遞迴優化 |
| `harness2-setup` | 安裝特定 Benchmark (`jb` JobBench / `lab` Legal / `wb` WorkBuddy) 與相依環境 |
| `harness2-check` | 執行事前環境、憑證與設定完整性檢查 (`Preflight Check`) |
| `harness2-judge` | 在選擇完成後呼叫評審模型進行打分（支援 `--bases` 評分基準組） |
| `harness2-report` | 彙整 `runs/` 下的評估結果並輸出統計報表 |
| `harness2-bridge` | 啟動本地 LiteLLM Proxy 橋接器，將 Vertex AI Gemini 轉換為 Codex Responses API 格式 |

---

## 三、自訂領域 / 量化交易適配器 (`BenchmarkAdapter` 開發範式)

若要將 Harness² 的 `Propose–Probe–Compose` 雙層遞迴引擎應用於**台股/美股量化策略開發、特徵工程腳本自動除錯或看盤報表生成**，只需實作 `harness2.core.spec.BenchmarkAdapter` 介面（詳見內建腳本 `scripts/quant_harness2_runner.py`）：

```python
# 執行本技能內建之「Harness² 量化對帳與策略自動演化實證引擎」並產出 ECharts HTML 報表：
python "C:\Users\Anu\.gemini\config\skills\harness2\scripts\quant_harness2_runner.py" `
  --k 2 `
  --output "D:\Python\_tmp\Harness2_Recursive_Agent_Report.html" `
  --backup "C:\Users\Anu\orca\projects\stock\Harness2_Recursive_Agent_Report.html"
```
