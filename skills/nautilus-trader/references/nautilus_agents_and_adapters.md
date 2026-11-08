# NautilusTrader (v2.x) 官方 AGENTS.md 與 ADAPTERS.md 權威參考指南

本文件彙整自 `https://github.com/nautechsystems/nautilus_trader` 官方倉庫之 `AGENTS.md`、`ADAPTERS.md` 與 v2.0 PyO3 API 規範。

---

## 1. 官方 Agent 開發守則 (`AGENTS.md`)

1. **實盤資金安全最高標準**：
   - NautilusTrader 直接控制真實資金進行實盤交易，任何程式碼變更均須符合最高標準的正確性 (Correctness)、可靠性 (Reliability)、可測試性 (Testing) 與清晰度。
2. **精確算術 (Exact Arithmetic)**：
   - 嚴禁對價格 (`Price`)、數量 (`Quantity`)、金額 (`Money`)、手續費 (`Fee`) 等離散金融數值使用一般浮點數運算；一律使用 Nautilus 領域型別（128-bit High-Precision 固定點整數）或 Python `Decimal`。
3. **跨平台路徑可攜性**：
   - 確保腳本與路徑在 Linux、macOS 與 Windows 上皆可正常運作，切勿單純以 `'/'` 分割路徑字串。
4. **開發環境 (`uv` 與 `python/.venv`)**：
   - 在開發核心倉庫時，使用 `python/.venv` 下由 `uv` 管理的虛擬環境；一般使用者安裝則建議使用官方預編譯之 128-bit High-Precision Binary Wheel (`pip install -U nautilus_trader --pre`)。

---

## 2. NautilusTrader v2.0 PyO3 核心匯入路徑對照表

在 `nautilus_trader >= 2.0.0rc7` (Rust-native PyO3 v2 Runtime) 中，頂層模組匯入大幅精簡：

```python
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, StrategyConfig
from nautilus_trader.core.datetime import dt_to_unix_nanos, unix_nanos_to_dt
from nautilus_trader.execution import PerContractFeeModel
from nautilus_trader.indicators import ExponentialMovingAverage
from nautilus_trader.model import (
    AccountType,
    AssetClass,
    Bar,
    BarType,
    Currency,
    Equity,
    FuturesContract,
    InstrumentId,
    Money,
    OmsType,
    OrderSide,
    Price,
    Quantity,
    Symbol,
    TimeInForce,
    TraderId,
    Venue,
)
from nautilus_trader.trading import Strategy
```

---

## 3. 官方與社群 Adapters 一覽表 (`ADAPTERS.md`)

### 官方 Adapters (Official Tier)
| Adapter 名稱 | Client ID | 類型 | 狀態 |
| :--- | :--- | :--- | :---: |
| **Interactive Brokers** | `INTERACTIVE_BROKERS` | 多市場綜合券商 (美股/期貨/外匯/選擇權) | Stable |
| **Binance** | `BINANCE` | 加密貨幣現貨與合約交易所 (CEX) | Stable |
| **Bybit** | `BYBIT` | 加密貨幣現貨與合約交易所 (CEX) | Stable |
| **Coinbase** | `COINBASE` | 加密貨幣交易所 (CEX) | Stable |
| **OKX** | `OKX` | 加密貨幣交易所 (CEX) | Stable |
| **Kraken** | `KRAKEN` | 加密貨幣交易所 (CEX) | Stable |
| **Deribit** | `DERIBIT` | 加密貨幣選擇權與衍生品交易所 | Stable |
| **Hyperliquid** | `HYPERLIQUID` | 去中心化永續合約交易所 (DEX) | Stable |
| **dYdX** | `DYDX` | 去中心化衍生品交易所 (DEX) | Stable |
| **Lighter** | `LIGHTER` / `LIGHTER_ROBINHOOD` | 去中心化交易所 (DEX) | Stable |
| **Derive** | `DERIVE` | 去中心化衍生品交易所 (DEX) | Stable |
| **Databento** | `DATABENTO` | 機構級美股/期貨 L1/L2/L3 歷史與即時行情源 | Stable |
| **Tardis** | `TARDIS` | 加密貨幣 Tick / OrderBook 歷史資料源 | Stable |
| **Polymarket** | `POLYMARKET` | 去中心化預測市場 (Prediction Market DEX) | Stable |
| **Betfair** | `BETFAIR` | 博弈交易所 | Stable |
| **AX Exchange** | `AX` | 衍生品交易所 | Stable |

### 社群 Adapters (Community Tier)
| 專案名稱 | 說明 | 維護者 | 連結 |
| :--- | :--- | :--- | :--- |
| **sinopac-nt-community** | **台灣永豐金證券 (SinoPac / Shioaji) 台股與台指期 Adapter** | Martingale42 | `https://github.com/Martingale42/sinopac-nt-community` |
| **mt5-connector** | MetaTrader 5 交易與報價介面 | aulekator | `https://github.com/aulekator/mt5-connector` |
| **tickerall-nt-community** | MetaTrader 5 行情資料介面 | Miguel Santos | `https://github.com/miguelangelo78/tickerall-nt-community` |
