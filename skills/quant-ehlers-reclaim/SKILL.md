---
name: quant-ehlers-reclaim
description: Implements the Adaptive Ehlers Filtered Percentile Reclaim (Plan B 1.0x) quantitative trading indicator and strategy (DSP Volatility-Adaptive EMA + Nonlinear Ehlers Distance-Weighted Smoothing + Nearest-Rank Percentile Bands + LowerBand False-Breakdown Reclaim Entry + Dual-Stage Mid-Lower Take-Profit Exit). Generates interactive HTML performance dashboards, signal audits, and Pine Script v5 code.
---

# Adaptive Ehlers Percentile Reclaim Engine (方案 B 1.0x 純現貨量化引擎)

## Overview
This skill implements the **Adaptive Ehlers Percentile Reclaim System (Plan B 1.0x)**, an institutional-grade quantitative trading model engineered to resolve the classic dilemma between trend-following lag and buy-and-hold risk.

The core architecture combines:
1. **Volatility-Adaptive Exponential Moving Average (AMA)**:
   - Uses 9-bar standard deviation of price changes mapped dynamically between 3 and 30 bars.
   - Smooths out noise during low-volatility consolidations while speeding up reaction during explosive momentum breakouts.
2. **Nonlinear Ehlers Distance-Weighted Smoothing (TrendMA)**:
   - Eliminates standard moving average lag by weighting past bars based on 15-bar momentum absolute differences.
3. **Nearest-Rank 75th Percentile Dynamic Channels**:
   - Calculates dynamic $\pm 0.7 \times \text{Percentile}$ envelopes around TrendMA using 50-bar rolling nearest-rank deviation sampling.
4. **Plan B (1.0x Pure Spot) Trading Logic**:
   - **Entry (破底翻抄底訊號)**: When price closes below `LowerBand` during a purple bearish regime, entry triggers on the **first bar closing back above `LowerBand`** (Next-Day Open execution).
   - **Dual-Stage Exit (階梯式分段防守/停利)**:
     - *Stage 1 (Bottom Stage before reaching UpperBand)*: Stop loss is strictly at `LowerBand` (tight, low-risk stop, average loss under -2%).
     - *Stage 2 (Major Bull Run confirmed after crossing UpperBand)*: The trailing exit floor automatically ratchets up to **Mid-Lower Band** $\frac{\text{TrendMA} + \text{LowerBand}}{2}$, locking in peak profits and preventing massive profit giveback.
   - **100% Pure Spot, Zero Leverage**: Fully unleveraged, 1.0x allocation.

---

## Benchmark Performance on ^TWII (Golden Parameters / 零槓桿純現貨)

> Backtests start **flat**: no position until the strategy fires its own first reclaim buy signal (positions held during the warm-up year are not inherited). No trading costs are deducted.

### 1. 過去 3 年核心基準 (2023-10-01 ~ 2026-10-08)
| Metric | Plan B (1.0x Golden Params) | Buy & Hold Benchmark | Note |
| :--- | :---: | :---: | :--- |
| **Total Return** | **+220.42%** | +201.54% | 超額報酬 +18.88 個百分點（總報酬相減，非 Alpha） |
| **Alpha (annualised, Jensen)** | **+18.44%** (t = 2.76) | 0.00% | β = 0.57；日報酬對大盤迴歸的截距 ×252 |
| **CAGR** | **+47.10%** | +44.17% | |
| **Max Drawdown (MDD)** | **-13.55%** | -28.69% | 回撤深度約為大盤一半 |
| **Calmar Ratio (CAGR/MDD)** | **3.48** | 1.54 | |
| **Sharpe Ratio** | **2.36** | 1.84 | |
| **Win Rate** | **57.9%** (11勝 / 8負) | — | |
| **Profit Factor** | **8.12** | — | |
| **Trades Count** | **19 Trades** | 1 Trade | 年均約 6 筆 |

### 2. 全週期歷史跨期驗證 (2023-01-01 ~ 2026-10-08)
| Metric | Plan B (1.0x Golden Params) | Buy & Hold Benchmark | Note |
| :--- | :---: | :---: | :--- |
| **Total Return** | **+231.95%** | +248.81% | 超額報酬 -16.86 個百分點：首次買進訊號在 2023-04-24，空手錯過 1–4 月漲幅 |
| **Alpha (annualised, Jensen)** | **+14.04%** (t = 2.50) | 0.00% | β = 0.55 |
| **CAGR** | **+37.57%** | +39.39% | |
| **Max Drawdown (MDD)** | **-13.55%** | -28.69% | |
| **Calmar Ratio (CAGR/MDD)** | **2.77** | 1.37 | |
| **Sharpe Ratio** | **2.13** | 1.67 | |
| **Win Rate** | **52.2%** (12勝 / 11負) | — | |
| **Trades Count** | **23 Trades** | 1 Trade | |

結果會隨起始日不同而變：2023-10-01 起始時策略剛好有訊號，報酬勝過大盤；2023-01-01 起始則因空手近 4 個月而落後大盤，但回撤仍只有大盤的一半。

---

## Files in this Skill

- **CLI Engine & Dashboard Generator**: [`scripts/ehlers_reclaim_engine.py`](scripts/ehlers_reclaim_engine.py)
- **HTML Report Template** (filled by the engine): [`scripts/report_template.html`](scripts/report_template.html)
- **TradingView Pine Script v5 / v6 Strategy**: [`scripts/ehlers_reclaim_strategy.pine`](scripts/ehlers_reclaim_strategy.pine)
- **Mathematical Specification**: [`references/documentation.md`](references/documentation.md)

---

## Usage

Use this skill whenever the user asks for:
- "方案 B 1.0x", "Ehlers 破底翻策略", "Adaptive Ehlers Filtered Percentile"
- Backtesting or running the Adaptive Ehlers Reclaim strategy on any ticker (e.g. `^TWII`, `0050.TW`, `SPY`, `QQQ`, `SMH`, `TSM`)
- Generating the interactive HTML backtest report (K線 + 通道 + 買賣點 + 權益/回撤 + 交易明細 + 目前出場線) or trade audit logs
- Exporting or integrating the TradingView Pine Script strategy

### 1. Run Quantitative Backtest via CLI

```bash
# Analyze ^TWII with Plan B (1.0x Golden Params)
python skills/quant-ehlers-reclaim/scripts/ehlers_reclaim_engine.py --symbol ^TWII --start 2023-10-01 --end 2026-10-08

# Analyze 0050 ETF or Taiwan Semiconductor
python skills/quant-ehlers-reclaim/scripts/ehlers_reclaim_engine.py --symbol 0050.TW --start 2023-10-01 --end 2026-10-08

# Analyze US Tech (QQQ or SMH)
python skills/quant-ehlers-reclaim/scripts/ehlers_reclaim_engine.py --symbol QQQ --start 2023-10-01 --end 2026-10-08
```

### CLI Arguments:
- `--symbol`: Ticker symbol (default: `^TWII`).
- `--start`: Start date `YYYY-MM-DD` (default: `2023-01-01`).
- `--end`: End date `YYYY-MM-DD` (default: `2026-10-08`).
- `--mode`: Strategy mode:
  - `plan_b_1x` (Recommended / 方案 B 1.0x 純現貨): Dual-stage mid-lower trailing exit.
  - `plan_a_1x` (方案 A 1.0x 現貨): LowerBand 1.5% hysteresis buffer stop.
  - `plan_b_12x` (方案 B 1.20x 微槓桿): Bull boost on Green regime.
- `--out`: Custom output path for the HTML report (default: `<symbol>_ehlers_<mode>_<start>_<end>.html` in the current directory).
- `--no-html`: Print the console summary only.

### 2. Interactive HTML Report

Every run (unless `--no-html`) writes one self-contained HTML file for the selected `--mode` (`compare` reports Plan B 1.0x).
It loads ECharts 5.5.0 from cdnjs, so it needs internet access when opened; all data is embedded in the page. It contains:

- **KPI strip**: total return vs Buy & Hold, excess return (total-return difference), annualised Jensen alpha with β and t-stat, CAGR, max drawdown, Calmar (CAGR / |MaxDD|), Sharpe/Sortino, win rate, profit factor/payoff.
- **Current position card**: holding/flat on the last bar, the active exit floor (stage 1 = LowerBand stop, stage 2 = 0.6×TrendMA + 0.4×LowerBand take-profit; Plan A = LowerBand×0.985), distance to it, and the bands.
- **Three synced panels** (shared zoom + crosshair tooltip): Taiwan-convention candlesticks (red up / green down) with TrendMA, Upper/Lower bands, the exit floor while held, held-period shading and buy/sell markers at the execution bar; cumulative return vs Buy & Hold; drawdown. Range buttons 3M / 6M / 1Y / All.
- **Trade ledger**: click a row to zoom the chart to that trade. `bars` is calendar days.
- **Caveats**: the backtest starts flat and waits for the first real buy signal (return is 0 until then), no costs are deducted, and the default parameters were tuned on ^TWII.
- Light / dark theme follows the viewer.

When presenting results, also relay the caveats above; the console numbers do not deduct trading costs.
