---
name: nautilus-trader
description: >
  基於 Nautech Systems 官方開源之 Rust + Python 機構級事件驅動量化交易與高頻回測引擎 NautilusTrader
  (https://github.com/nautechsystems/nautilus_trader, v2.x 128-bit High-Precision 架構)。
  支援單一程式碼同時運行於奈秒級決定性事件驅動回測 (BacktestEngine / BacktestNode) 與實盤交易 (TradingNode)，
  涵蓋多市場/多交易所 Adapter (Interactive Brokers、Binance、Bybit、Hyperliquid、Databento 及台股永豐金 SinoPac 社群介面)、
  高精度領域型別 (Price / Quantity / Money / InstrumentId / BarType)、策略生命週期 (Strategy / Actor / ExecAlgorithm)
  與機構級 ECharts 互動式 HTML 回測報表輸出。當使用者提及「NautilusTrader」、「nautilus_trader」、
  「事件驅動回測 (Event-Driven Backtest)」、「TradingNode / BacktestEngine」時自動觸發。
---

# NautilusTrader — 華爾街機構級 Rust+Python 事件驅動量化交易與回測引擎技能

本技能完整封裝 [nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader) 官方架構規範、開發守則 (`AGENTS.md`)、高精度領域模型 (`nautilus_model`) 與事件驅動策略開發流程，並結合本工作區之深色機構級 ECharts HTML 報表規範，提供從歷史行情轉換、事件驅動策略回測到實盤部署的一致化管線。

---

## 一、核心架構與設計哲學 (Core Architecture & Design Philosophy)

1. **Rust 原生核心 + Python 控制平面 (Rust Core + Python Control Plane via PyO3)**：
   - 底層核心（`nautilus-core`、`nautilus-model`、`nautilus-common`、`nautilus-execution`、`nautilus-backtest`）採用 Rust 撰寫，搭配 `mimalloc` 記憶體配置器與 `tokio` 非同步網路，提供型別安全、執行緒安全與奈秒級 (`UnixNanos`) 時間解析度。
   - Python 透過 PyO3 綁定作為策略邏輯 (`Strategy`)、組態設定 (`Config`) 與系統編排 (`BacktestEngine` / `TradingNode`) 的控制平面。
2. **回測與實盤零差異 (Research-to-Live Parity)**：
   - 同一份 `Strategy`、`Actor` 與執行演算法 (`ExecAlgorithm`) 程式碼，無須重寫即可直接由 `BacktestEngine` 切換至 `TradingNode` 實盤運行，徹底消除傳統「向量化研究 (Vectorized Research) vs. 事件驅動實盤 (Event-Driven Production)」的落差。
3. **128-bit 高精度固定點算術 (Precision Mode & Exact Arithmetic)**：
   - 官方 Python Wheel 預設啟用 **High-Precision Mode (128-bit integers，最高 16 位小數精度)**。
   - **嚴格算術鐵律 (來自官方 `AGENTS.md`)**：所有價格 (`Price`)、數量 (`Quantity`)、金額 (`Money`) 與手續費必須使用 Nautilus 領域型別或 `Decimal` 精確計算，嚴禁使用浮點數誤差進行委託單比價或倉位結算。
4. **六大核心子系統 (Core Engine Components)**：
   - **`MessageBus`**：中樞神經系統，負責點對點訊息傳遞與 Pub/Sub 主題訂閱。
   - **`Cache`**：高速記憶體快取（支援選配 Redis 持久化），儲存 `Instrument`、`OrderBook`、`QuoteTick`、`TradeTick`、`Bar`、`Order`、`Position` 與 `Account` 狀態。
   - **`DataEngine`**：處理市場行情訂閱、聚合 K 線 (`BarAggregation`) 與歷史資料回放。
   - **`RiskEngine`**：在委託送出前執行毫秒級事前風控（最大委託量、名目價值上限、下單頻率節流、Reduce-Only 檢查）。
   - **`ExecutionEngine`**：管理委託單生命週期 (`OrderSubmitted` $\rightarrow$ `OrderAccepted` $\rightarrow$ `OrderFilled` / `OrderCanceled`) 與倉位淨額/對沖模式 (`OmsType.NETTING` / `OmsType.HEDGING`)。
   - **`Portfolio`**：即時計算跨幣別/跨市場之已實現損益 (`Realized PnL`)、未實現損益 (`Unrealized PnL`)、維持保證金與淨值曝險。

---

## 二、支援之交易所與資料源 Adapters (`ADAPTERS.md`)

### 1. 官方維護 Adapters (Official Tier)
| 類別 | 支援平台與 Client ID |
| :--- | :--- |
| **傳統金融與多資產券商** | **Interactive Brokers (`INTERACTIVE_BROKERS`)**、**AX Exchange (`AX`)** |
| **加密貨幣中心化交易所 (CEX)** | **Binance (`BINANCE`)**、**Bybit (`BYBIT`)**、**Coinbase (`COINBASE`)**、**OKX (`OKX`)**、**Kraken (`KRAKEN`)**、**Deribit (`DERIBIT`)** |
| **去中心化交易所與鏈上衍生品 (DEX)** | **Hyperliquid (`HYPERLIQUID`)**、**dYdX (`DYDX`)**、**Lighter (`LIGHTER` / `LIGHTER_ROBINHOOD`)**、**Derive (`DERIVE`)** |
| **機構級歷史與即時行情源** | **Databento (`DATABENTO`)**、**Tardis (`TARDIS`)**、**Blockchain (`BLOCKCHAIN`)** |
| **預測市場與博弈交易所** | **Polymarket (`POLYMARKET`)**、**Betfair (`BETFAIR`)**、**Kalshi (`KALSHI`)** |

### 2. 台灣市場與社群 Adapters (Community Tier)
* **永豐金證券台股/期貨介面 (`sinopac-nt-community`)**：串接台灣永豐金 Shioaji API，支援台股現貨與台灣期交所 (TAIFEX) 期貨/選擇權之行情與下單。
* **MetaTrader 5 (`mt5-connector` / `tickerall-nt-community`)**：串接 MT5 外匯與差價合約 (CFD) 報價與交易。

---

## 三、NautilusTrader 標準策略與回測開發範式 (Strategy & Backtest Pattern)

### 1. 策略組態與生命週期 (`StrategyConfig` & `Strategy`)
在 NautilusTrader 中，所有策略皆繼承自 `nautilus_trader.trading.strategy.Strategy`，並搭配不可變組態 `StrategyConfig`：

```python
from decimal import Decimal
from nautilus_trader.config import StrategyConfig
from nautilus_trader.core.message import Event
from nautilus_trader.indicators import ExponentialMovingAverage
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy

class EMACrossConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    trade_size: Decimal
    fast_ema_period: int = 20
    slow_ema_period: int = 60

class EMACrossStrategy(Strategy):
    def __init__(self, config: EMACrossConfig) -> None:
        super().__init__(config)
        self.fast_ema = ExponentialMovingAverage(config.fast_ema_period)
        self.slow_ema = ExponentialMovingAverage(config.slow_ema_period)

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        # 註冊指標隨 Bar 自動更新，並訂閱行情
        self.register_indicator_for_bar(self.config.bar_type, self.fast_ema)
        self.register_indicator_for_bar(self.config.bar_type, self.slow_ema)
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        if not self.indicators_initialized():
            return
        # 黃金交叉買進 / 死亡交叉平倉
        if self.fast_ema.value > self.slow_ema.value and self.portfolio.is_flat(self.config.instrument_id):
            order = self.order_factory.market(
                instrument_id=self.config.instrument_id,
                order_side=OrderSide.BUY,
                quantity=self.instrument.make_qty(self.config.trade_size),
                time_in_force=TimeInForce.GTC,
            )
            self.submit_order(order)
        elif self.fast_ema.value < self.slow_ema.value and self.portfolio.is_net_long(self.config.instrument_id):
            self.close_all_positions(self.config.instrument_id)

    def on_Event(self, event: Event) -> None:
        pass

    def on_stop(self) -> None:
        self.cancel_all_orders(self.config.instrument_id)
        self.close_all_positions(self.config.instrument_id)
```

### 2. 低階回測引擎組裝流程 (`BacktestEngine`)
1. 建立 `BacktestEngine(config=BacktestEngineConfig(trader_id=TraderId("BACKTESTER-001")))`。
2. 呼叫 `engine.add_venue(...)` 設定交易所 (`Venue`)、OMS 模式 (`OmsType.NETTING` 或 `HEDGING`)、帳戶類型 (`AccountType.MARGIN` 或 `CASH`) 與初始資金 (`[Money(1_000_000, USD)]`)。
3. 呼叫 `engine.add_instrument(instrument)` 註冊商品合約規格（最小跳動點 `price_increment`、最小數量 `size_increment`）。
4. 使用 `BarDataWrangler` 或 `QuoteTickDataWrangler` 將 Pandas DataFrame 轉換為 Nautilus 原生 `Bar` / `QuoteTick` 物件，並透過 `engine.add_data(bars)` 注入引擎。
5. 呼叫 `engine.add_strategy(strategy)` 掛載策略，執行 `engine.run()`。
6. 透過 `engine.trader.generate_order_fills_report()`、`engine.trader.generate_positions_report()` 與 `engine.trader.generate_account_report(venue)` 擷取完整機構級對帳報表。

---

## 四、自動化執行腳本與互動式 HTML 報表引擎

本技能內建可直接執行的事件驅動回測與 HTML 視覺化腳本 `scripts/nautilus_backtest_runner.py`，能自動抓取任意台股（如 `2330.TW`、`0050.TW`、`00631L.TW`）或美股（如 `NVDA`、`SOXX`、`SPY`）歷史日線/分時資料，轉換為 NautilusTrader 原生 `Bar` 物件，在 `BacktestEngine` 內運行事件驅動雙均線 / 動態趨勢策略，並輸出符合 `AGENTS.md` 規範（紅漲綠跌、雙 CDN、通過 `node --check` 驗證）之三窗格互動式 ECharts HTML 回測終端報表。

### CLI 執行指令：
```powershell
python "C:\Users\Anu\.gemini\config\skills\nautilus-trader\scripts\nautilus_backtest_runner.py" `
  --symbol "00631L.TW" `
  --fast-ema 20 `
  --slow-ema 60 `
  --capital 1000000 `
  --output "D:\Python\_tmp\NautilusTrader_Backtest_Report.html" `
  --backup "C:\Users\Anu\orca\projects\stock\NautilusTrader_Backtest_Report.html"
```

---

## 五、官方開發與貢獻守則摘要 (`references/nautilus_agents_policy.md`)
當協助使用者修改或擴充 `nautilus_trader` 核心原始碼或撰寫實盤策略時，務必遵循以下來自官方 `AGENTS.md` 之核心鐵律：
1. **精確算術**：所有價格、數量、金額、手續費一律使用專案領域型別 (`Price`, `Quantity`, `Money`) 或 `Decimal`。
2. **跨平台路徑正規化**：切勿單純使用 `'/'` 切割路徑，確保在 Linux、macOS 與 Windows 下皆具備可攜性。
3. **Jupyter / 大量回測日誌保護**：在回測巨量 Tick/Bar 時，將 `LoggingConfig(log_level="ERROR")` 或 `"WARNING"` 設為預設，避免高頻日誌塞爆標準輸出緩衝區。
