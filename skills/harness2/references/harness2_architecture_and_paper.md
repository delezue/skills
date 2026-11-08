# Harness² (`google-research/harness2`, arXiv:2610.14224) 權威架構與核心介面參考指南

本文件彙整自 Google Research 官方開源倉庫 [`google-research/harness2`](https://github.com/google-research/harness2) 與論文 *"Harness²: Recursive Agent Harnessing for an Open World"* (arXiv:2610.14224)。

---

## 1. 八大可編輯 Harness 組件 (`c1..c8` Editable Surface)

在 `harness2/core/tree.py` 與 `harness2/substrate/opencode.py` 中，Agent 的外骨骼被抽象為 `Tree = dict[str, str]`（相對路徑 $\rightarrow$ 檔案文字內容），涵蓋以下 8 個角色維度：

| 組件代號 | 檔案路徑規範 (`OpencodeSubstrate` / `CodexSubstrate`) | 執行期角色 (Runtime Role) |
| :---: | :--- | :--- |
| **c1** | `systemprompt.md` (或 `AGENTS.md`) | **Context Construction**：系統提示詞、核心角色與頂層推理策略 |
| **c2** | `guardrails.md` | **Context Construction**：安全護欄、禁止事項與交付前自我檢查清單 |
| **c3** | `LongTermMEMORY.md` | **Context Construction**：跨任務累積之領域知識、常見陷阱與解題記憶 |
| **c4** | `tool_descriptions/tool_guidance.md` | **Tool Interface**：工具選用策略、參數傳遞規範與錯誤復原指引 |
| **c5** | `sub_agents/<name>/AGENT.md` | **Orchestration**：專業子代理角色定義與任務委派分工 |
| **c6** | `skills/<name>/SKILL.md` (+ `scripts/*`) | **Context & Tooling**：模組化專業技能包（由 `tree.autotrigger()` 自動注入觸發條件） |
| **c7** | `scripts/<name>.py` | **Tool Interface**：決定性 Python 運算、資料清理、對帳與驗證腳本 |
| **c8** | `plugin/<name>.ts` / `hooks.json` | **Middleware**：工具呼叫前後之攔截器與事件鉤子 |

---

## 2. 任務層級遞迴 (`harness2/core/recursion.py`)

每個任務在 `k` 預算下會執行 **`4k` 次 Rollouts 與 `3k` 個 Improvement Stages**：

1. **平行遞迴 (`--mode parallel`)**：
   - 先執行 `k` 次 Base Harness 基準測試 (`base1..base_k`)。
   - **Propose & Probe**：同時提出並執行 `k` 個通用不變候選 (`inv1..inv_k`) 與 `k` 個領域專屬候選 (`dom1..dom_k`)。
   - **Compose**：從全部 `2k` 個候選探針與基準軌跡的共享證據池中，獨立合成出 `k` 個組合版 Harness (`comp1..comp_k`) 並執行驗證。
   - **Select**：由 Selector 根據產出物完整性與軌跡證據選出最佳採納版 (`chosen_label`)。
2. **序列遞迴 (`--mode sequential`)**：
   - 連續執行 `k` 輪 `Propose (inv + dom) -> Probe -> Compose` 步驟，每一輪將上一輪合成出的最佳 Harness 與累積執行證據傳遞至下一輪，適合需要多步深度除錯的複雜任務。

---

## 3. 駕馭層級遞迴與領域知識庫 (`harness2/core/library.py`)

每當一個任務完成擇優後，系統執行 `experience.<mode>` 階段：
- 比對 `base_harness` 與採納之 `adopted_harness` 在 `c1..c8` 樹上的 Diff。
- 解析 `<edits>`（哪個組件被修改、觀察到什麼行為改變、是否有效）與 `<experience>`（觸發線索 `cue`、核心教訓 `lesson`、軌跡證據 `evidence`、信心水準 `confidence`）。
- 寫入該領域 (`domain_of(task_id)`) 專屬的持久化知識庫，供後續同領域任務在 `context.build()` 時自動檢索引用。

---

## 4. 論文實證基準提升幅度 (arXiv:2610.14224)

在固定模型權重（GLM-5 與 Gemini 3.5 Flash）下，僅執行單步 Harness² 遞迴即可在三大專業基準測試大幅超越原始基準 Harness：
- **WorkBuddy-Bench (Office / Web / Code)**：提升最高達 **+11.5 分**
- **JobBench (Professional Occupational Tasks)**：提升最高達 **+4.5 分**
- **LAB (Legal Agent Benchmark)**：Partial Pass Rate 提升最高達 **+11.8 個百分點**
