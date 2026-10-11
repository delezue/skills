# Antigravity Quant Skills Library (量化技能庫)

此倉庫專門存放 Google Antigravity (AGY) 量化交易與分析相關之專業 Skills。

## 📦 已收錄技能清單

### 1. [`skill/quant-iwy-lead`](skill/quant-iwy-lead/)
- **名稱**：IWY 美股巨頭領先指標量化系統 (ZLEMA-BBI 13/21/34/55)
- **標的**：^TWII (台股加權指數) / 台股正二 (00685L) / 美股 IWY
- **核心邏輯**：利用美股凌晨 04:00 收盤確定訊號與台股上午 09:00 開盤之間的 5 小時時間差，實現嚴格 100% 因果時序、零未來函數之 Open-to-Open 實盤操作。
- **實盤回測成效 (^TWII 2023-10-01 ~ 2026-10-08)**：
  - 累積總報酬：**+218.39%** (同期大盤死抱 +197.83%)
  - 超額報酬 (Alpha)：**+20.56%**
  - 勝率：**66.2%** (51勝 / 26負)
  - 盈虧比：**3.94**
  - 最大回撤：**-7.49%** (大盤最大回撤 -28.69%)

---
*Created by [delezue](https://github.com/delezue)*
