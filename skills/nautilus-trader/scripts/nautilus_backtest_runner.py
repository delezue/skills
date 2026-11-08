#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NautilusTrader (v2.x) 華爾街機構級事件驅動回測與 ECharts 視覺化終端引擎
Skill: nautilus-trader
"""

import os
import sys
import json
import math
import argparse
import tempfile
import subprocess
import urllib.request
from datetime import datetime, UTC
from decimal import Decimal
from typing import Any, Self

import numpy as np
import pandas as pd

import nautilus_trader
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

USD = Currency.from_str("USD")


def fetch_yahoo_ohlcv(symbol: str, start_ts: int = 1414627200) -> pd.DataFrame:
    end_ts = int(datetime.now(UTC).timestamp()) + 86400
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(symbol)}?period1={start_ts}&period2={end_ts}&interval=1d&events=div,split"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    res = data['chart']['result'][0]
    ts = res['timestamp']
    q = res['indicators']['quote'][0]
    df = pd.DataFrame({
        'ts': ts,
        'date': [datetime.fromtimestamp(t, UTC).strftime('%Y-%m-%d') for t in ts],
        'open': q['open'],
        'high': q['high'],
        'low': q['low'],
        'close': q['close'],
        'volume': q['volume'],
    })
    df = df.dropna(subset=['open', 'high', 'low', 'close']).drop_duplicates(subset=['date'], keep='last').reset_index(drop=True)
    # Fix split jumps if any
    for col in ['open', 'high', 'low', 'close']:
        s = df[col].values.copy()
        for i in range(1, len(s)):
            ratio = s[i] / s[i - 1] if s[i - 1] > 0 else 1.0
            if ratio < 0.35 or ratio > 2.8:
                s[i:] = s[i:] / ratio
        df[col] = s
    # Ensure OHLC consistency
    df['high'] = df[['open', 'high', 'low', 'close']].max(axis=1)
    df['low'] = df[['open', 'high', 'low', 'close']].min(axis=1)
    df['volume'] = df['volume'].fillna(1000).clip(lower=1)
    return df


class NautilusEMACrossConfig(StrategyConfig):
    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        kwargs.pop("instrument_id", None)
        kwargs.pop("bar_type", None)
        kwargs.pop("fast_period", None)
        kwargs.pop("slow_period", None)
        kwargs.pop("trade_qty", None)
        return super().__new__(cls, *args, **kwargs)

    def __init__(
        self,
        instrument_id: InstrumentId,
        bar_type: BarType,
        fast_period: int = 20,
        slow_period: int = 60,
        trade_qty: int = 1000,
    ) -> None:
        super().__init__()
        self.instrument_id = instrument_id
        self.bar_type = bar_type
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.trade_qty = trade_qty


class NautilusEMACrossStrategy(Strategy):
    def __init__(self, config: NautilusEMACrossConfig) -> None:
        super().__init__(config)
        self._config = config
        self.fast_ema = ExponentialMovingAverage(config.fast_period)
        self.slow_ema = ExponentialMovingAverage(config.slow_period)
        self.telemetry_rows: list[dict[str, Any]] = []

    def on_start(self) -> None:
        self.subscribe_bars(self._config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        self.fast_ema.handle_bar(bar)
        self.slow_ema.handle_bar(bar)

        is_flat = self.portfolio.is_completely_net_flat()
        if self.fast_ema.initialized and self.slow_ema.initialized:
            if self.fast_ema.value > self.slow_ema.value and is_flat:
                order = self.order_factory.market(
                    instrument_id=self._config.instrument_id,
                    order_side=OrderSide.BUY,
                    quantity=Quantity.from_int(self._config.trade_qty),
                    time_in_force=TimeInForce.GTC,
                )
                self.submit_order(order)
            elif self.fast_ema.value < self.slow_ema.value and not is_flat:
                order = self.order_factory.market(
                    instrument_id=self._config.instrument_id,
                    order_side=OrderSide.SELL,
                    quantity=Quantity.from_int(self._config.trade_qty),
                    time_in_force=TimeInForce.GTC,
                )
                self.submit_order(order)

        r_pnl = self.portfolio.realized_pnl(self._config.instrument_id)
        u_pnl = self.portfolio.unrealized_pnl(self._config.instrument_id)
        r_val = float(r_pnl.as_double()) if r_pnl is not None else 0.0
        u_val = float(u_pnl.as_double()) if u_pnl is not None else 0.0

        self.telemetry_rows.append({
            'date': unix_nanos_to_dt(bar.ts_event).strftime('%Y-%m-%d'),
            'close': float(bar.close.as_double()),
            'fast_ema': round(float(self.fast_ema.value), 2) if self.fast_ema.initialized else None,
            'slow_ema': round(float(self.slow_ema.value), 2) if self.slow_ema.initialized else None,
            'realized_pnl': round(r_val, 2),
            'unrealized_pnl': round(u_val, 2),
            'total_pnl': round(r_val + u_val, 2),
            'in_pos': 0 if self.portfolio.is_completely_net_flat() else 1,
        })

    def on_stop(self) -> None:
        pass


def run_nautilus_backtest(symbol: str = '00631L.TW', fast_ema: int = 20, slow_ema: int = 60, init_cap: float = 1000000.0):
    df = fetch_yahoo_ohlcv(symbol)
    venue = Venue("SIM")
    raw_sym = Symbol(symbol.replace('.', '_'))
    inst_id = InstrumentId(raw_sym, venue)

    instrument = FuturesContract(
        instrument_id=inst_id,
        raw_symbol=raw_sym,
        asset_class=AssetClass.INDEX,
        currency=USD,
        price_precision=2,
        price_increment=Price.from_str("0.01"),
        multiplier=Quantity.from_int(1),
        lot_size=Quantity.from_int(1),
        underlying=symbol,
        activation_ns=0,
        expiration_ns=int(datetime(2035, 12, 31, tzinfo=UTC).timestamp() * 1e9),
        ts_event=0,
        ts_init=0,
        margin_init=Decimal("0.10"),
        margin_maint=Decimal("0.08"),
        exchange="SIM",
    )

    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id=TraderId.from_str("NAUTILUS-QUANT-001"),
        ),
    )
    engine.add_venue(
        venue=venue,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        fee_model=PerContractFeeModel(Money.from_str("0.01 USD")),
        starting_balances=[Money.from_str(f"{int(init_cap)} USD")],
    )
    engine.add_instrument(instrument)

    bar_type = BarType.from_str(f"{instrument.id}-1-DAY-LAST-EXTERNAL")
    bars = []
    for _, row in df.iterrows():
        dt_ns = dt_to_unix_nanos(datetime.strptime(row['date'], '%Y-%m-%d').replace(tzinfo=UTC))
        bars.append(
            Bar(
                bar_type=bar_type,
                open=instrument.make_price(float(row['open'])),
                high=instrument.make_price(float(row['high'])),
                low=instrument.make_price(float(row['low'])),
                close=instrument.make_price(float(row['close'])),
                volume=Quantity.from_int(int(row['volume'])),
                ts_event=dt_ns,
                ts_init=dt_ns,
            )
        )
    engine.add_data(bars)

    init_px = float(df['close'].iloc[0])
    trade_qty = max(1, int(init_cap / max(init_px, 1.0)))

    cfg = NautilusEMACrossConfig(
        instrument_id=instrument.id,
        bar_type=bar_type,
        fast_period=fast_ema,
        slow_period=slow_ema,
        trade_qty=trade_qty,
    )
    strategy = NautilusEMACrossStrategy(config=cfg)
    engine.add_strategy(strategy)
    engine.run()

    fills_df = engine.generate_order_fills_report()
    pos_df = engine.generate_positions_report()
    engine.dispose()

    print(f"[NautilusTrader v{nautilus_trader.__version__}] 完成 {symbol} 事件驅動回測！總成交筆數: {len(fills_df)}, 總倉位週期數: {len(pos_df)}")
    return {
        'version': nautilus_trader.__version__,
        'symbol': symbol,
        'fast_ema': fast_ema,
        'slow_ema': slow_ema,
        'init_cap': init_cap,
        'fills_count': len(fills_df),
        'positions_count': len(pos_df),
        'telemetry': strategy.telemetry_rows,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='NautilusTrader v2.x Event-Driven Backtest Runner')
    parser.add_argument('--symbol', type=str, default='00631L.TW')
    parser.add_argument('--fast-ema', type=int, default=20)
    parser.add_argument('--slow-ema', type=int, default=60)
    parser.add_argument('--capital', type=float, default=1000000.0)
    args = parser.parse_args()
    res = run_nautilus_backtest(args.symbol, args.fast_ema, args.slow_ema, args.capital)
    last_row = res['telemetry'][-1]
    print(f"期末累積總損益 (Total PnL): {last_row['total_pnl']:+,.2f} | 期末總權益: {args.capital + last_row['total_pnl']:,.2f}")
