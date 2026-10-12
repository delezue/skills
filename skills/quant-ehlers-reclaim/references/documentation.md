# Adaptive Ehlers Percentile Reclaim Strategy (Plan B 1.0x) Mathematical & Quantitative Specification

## 1. Indicator Mathematics

### 1.1 Volatility-Adaptive Moving Average (AMA)
Let $P_t = \text{Close}_t$, $\Delta P_t = P_t - P_{t-1}$.
The rolling sample standard deviation of price changes across volatility length $L_{\text{vol}} = 9$:
$$s_t = \sqrt{\frac{1}{L_{\text{vol}} - 1} \sum_{k=0}^{L_{\text{vol}}-1} (\Delta P_{t-k} - \overline{\Delta P}_t)^2}$$
$$\overline{s}_t = \frac{1}{L_{\text{vol}}} \sum_{k=0}^{L_{\text{vol}}-1} s_{t-k}$$
Dynamic boundaries:
$$s_{\min, t} = 0.25 \, \overline{s}_t, \quad s_{\max, t} = 1.75 \, \overline{s}_t, \quad \text{VolRange}_t = s_{\max, t} - s_{\min, t}$$
The dynamic adaptive smoothing length is linearly interpolated between $L_{\min} = 3$ and $L_{\max} = 30$:
$$\text{Length}_t = \begin{cases} L_{\max} & \text{if } s_t \le s_{\min, t} \\ L_{\min} & \text{if } s_t \ge s_{\max, t} \\ L_{\max} - (L_{\max} - L_{\min}) \cdot \frac{s_t - s_{\min, t}}{\text{VolRange}_t} & \text{otherwise} \end{cases}$$
The recursive smoothing factor $\alpha_t = \frac{2}{\text{Length}_t + 1}$, yielding:
$$\text{AMA}_t = \text{AMA}_{t-1} + \alpha_t (P_t - \text{AMA}_{t-1})$$

### 1.2 Nonlinear Ehlers Distance-Weighted Smoothing
Across an Ehlers window $L_E = 9$ with momentum lookback $M_E = 15$:
$$w_i = |\text{AMA}_{t-i} - \text{AMA}_{t-i-M_E}|$$
$$\text{TrendMA}_t = \frac{\sum_{i=0}^{L_E - 1} w_i \cdot \text{AMA}_{t-i}}{\sum_{i=0}^{L_E - 1} w_i}$$

### 1.3 Nearest-Rank 75th Percentile Dynamic Channel
Deviation series: $D_t = |P_t - \text{TrendMA}_t|$.
Percentile distance:
$$\text{PctDist}_t = \text{Percentile}_{\text{nearest}}(D_{t-49 \dots t}, 75.0)$$
Channel bands with multiplier $m = 0.7$:
$$\text{UpperBand}_t = \text{TrendMA}_t + 0.7 \cdot \text{PctDist}_t$$
$$\text{LowerBand}_t = \text{TrendMA}_t - 0.7 \cdot \text{PctDist}_t$$

---

## 2. Plan B (1.0x Pure Spot) Trading Logic

### 2.1 Entry Trigger (False-Breakdown Reclaim)
- Condition 1: Market in Bearish Regime ($SQ = -1$, Purple Bar).
- Condition 2: Price previously closed below $\text{LowerBand}$ ($P_{\tau} < \text{LowerBand}_{\tau}$).
- Buy Signal: First bar where $P_t > \text{LowerBand}_t$.
- Execution: Buy 100% spot at Open of bar $t+1$.

### 2.2 Dual-Stage Exit Floor (Locked-in Peak Profits)
- Stage 1 (Before reaching $\text{UpperBand}$):
  $$\text{ExitFloor}_t = \text{LowerBand}_t$$
  If $P_t < \text{ExitFloor}_t$, stop loss triggered.
- Stage 2 (After confirming major bull run, i.e. $P > \text{UpperBand}$ established):
  $$\text{ExitFloor}_t = \frac{\text{TrendMA}_t + \text{LowerBand}_t}{2}$$
  If $P_t < \text{ExitFloor}_t$, take-profit exit triggered.
- Execution: Sell 100% position to cash at Open of bar $t+1$.

---

## 3. Backtest Performance Summary (^TWII Golden Parameters 1.0x Pure Spot)

All backtests start flat and enter only on the strategy's own first buy signal. Strategy figures are net of a 0.3% round-trip cost (`--cost 0.3`); Buy & Hold is gross.

### Past 3 Years (2023-10-01 ~ 2026-10-08)
| Metric | Plan B (1.0x, 0.3% cost) | Buy & Hold Benchmark |
| :--- | :---: | :---: |
| Total Return | **+203.11%** (gross +220.42%) | +201.54% |
| Excess Return (total-return difference) | **+1.57%** | 0.00% |
| Alpha (annualised Jensen, β = 0.57, t = 2.47) | **+16.47%** | 0.00% |
| CAGR | **+44.42%** | +44.17% |
| Max Drawdown | **-16.12%** | **-28.69%** |
| Calmar Ratio (CAGR/MDD) | **2.76** | 1.54 |
| Sharpe Ratio | **2.25** | 1.84 |
| Win Rate | **52.6%** | — |
| Profit Factor | **6.97** | — |
| Trades Count | **19 Trades** | 1 Trade |

### Full Period Cross-Validation (2023-01-01 ~ 2026-10-08)
| Metric | Plan B (1.0x, 0.3% cost) | Buy & Hold Benchmark |
| :--- | :---: | :---: |
| Total Return | **+210.26%** (gross +231.95%) | +248.81% |
| Excess Return (total-return difference) | **-38.55%** | 0.00% |
| Alpha (annualised Jensen, β = 0.56, t = 2.16) | **+12.11%** | 0.00% |
| CAGR | **+35.12%** | +39.39% |
| Max Drawdown | **-16.12%** | **-28.69%** |
| Calmar Ratio (CAGR/MDD) | **2.18** | 1.37 |
| Sharpe Ratio | **2.01** | 1.67 |
| Win Rate | **47.8%** | — |
| Profit Factor | **6.01** | — |
| Trades Count | **23 Trades** | 1 Trade |

### Metric Definitions
- **Excess Return** = strategy total return − Buy & Hold total return (percentage points). This is *not* alpha.
- **Alpha (Jensen, annualised)**: OLS of daily strategy returns on daily benchmark returns, $r_s = \alpha + \beta\,r_m + \varepsilon$ (risk-free rate taken as 0); reported as $\alpha \times 252$. `alpha_t` is the t-statistic of the intercept; `beta` is the average market exposure.
- **Calmar Ratio** = CAGR / |Max Drawdown|. (Earlier versions used total return / MDD, which grows with the length of the test window and is not comparable across periods.)
- **Start state**: the backtest begins flat (`curr_pos = 0`). Earlier versions started fully invested on the first bar regardless of the signal, which added ~34.5 points of return on 2023-01-01 ~ 2026-10-08 (start-state bias).
- **Trading cost** (`cost_rt`, CLI `--cost` in percent, default 0.3): round-trip cost covering commission, transaction tax and slippage. Half is deducted from the daily return on the entry day and half on the exit day (scaled by position size); ledger trade returns are net (an open trade has only paid the entry half). Buy & Hold is left gross.
