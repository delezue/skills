---
name: quant-iwy-lead
description: Runs the IWY ZLEMA-BBI leading indicator quantitative strategy to generate actionable long/short/hold signals for TWII (Taiwan Stock Market).
---

# IWY ZLEMA-BBI Leading Indicator (美股巨頭領先指標量化系統)

## Overview
This skill generates an actionable daily HTML dashboard to guide trading for the Taiwan Stock Market (specifically leveraged ETFs like 00685L) using the iShares Russell Top 200 Growth ETF (IWY) as a time-leading indicator.

It uses a proprietary Zero-Lag Exponential Moving Average Bull-Bear Index (ZLEMA-BBI 13/21/34/55) to eliminate indicator lag. Because the US market closes at 04:00 AM Taiwan time, the signal is 100% known before the Taiwan market opens at 09:00 AM, allowing for realistic Open-to-Open execution without look-ahead bias.

## Usage

1. **Daily Signal Health Check**:
   ```bash
   python .agents/skills/quant-iwy-lead/scripts/generate_signal.py
   ```
   Outputs `iwy_signal_dashboard.html` with current daily guidance.

2. **Professional Interactive K-Line HTML Dashboard for ^TWII (Custom Period)**:
   ```bash
   python .agents/skills/quant-iwy-lead/scripts/generate_twii_kline.py --start 2023-10-01 --end 2026-10-08 --out TWII_IWY_Lead_Dashboard_2023_2026.html
   ```
   Generates a 3-subplot interactive Plotly K-line dashboard mapping US IWY leading signals directly onto `^TWII` price action and realistic Open-to-Open execution.

## Interpretation of Signals
- **剛轉多頭 (黃金交叉) / 🚀 建倉**: IWY just crossed above the ZLEMA-BBI. The user should deploy cash to buy the Taiwan market (e.g., 00685L) at the next open.
- **多頭格局 (穩健) / 📈 持有**: IWY remains safely above the BBI. The user should hold their positions.
- **剛轉空頭 (死亡交叉) / 🚨 清倉**: IWY just crossed below the ZLEMA-BBI. The user must sell/reduce Taiwan market positions at the next open to avoid a potential crash.
- **空頭弱勢 / 📉 空手觀望**: IWY remains below the BBI. The user should hold cash and NOT try to catch falling knives.

## Dependencies
- `yfinance`
- `pandas`
- `numpy`
