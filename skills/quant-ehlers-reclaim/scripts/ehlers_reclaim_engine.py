#!/usr/bin/env python3
"""
Adaptive Ehlers Filtered Percentile Reclaim (Plan B 1.0x) Quantitative Engine
Implements:
  1. Volatility-Adaptive EMA (StDev dynamic mapping: 3 ~ 30 bars)
  2. Ehlers Distance-Weighted Momentum Smoothing (TrendMA)
  3. Nearest-Rank 75th Percentile Dynamic Channels (UpperBand & LowerBand)
  4. LowerBand False-Breakdown Reclaim Entry (破底翻站回下軌買進)
  5. Dual-Stage Mid-Lower Take-Profit Exit (衝出上軌後改破中下軌中點停利離場)
"""

import argparse
import html
import json
import sys
import os
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def run_ehlers_percentile(df, ma_min=3, ma_max=30, vol_len=12,
                          ehlers_len=9, ehlers_mom=12,
                          pct_len=40, pct_level=75.0,
                          upper_mult=0.7, lower_mult=0.8):
    """
    Vectorized calculation of the Adaptive Ehlers Filtered Percentile Indicator.
    Zero-Lookahead Bias guaranteed.
    """
    close = df['Close'].values.astype(float)
    n = len(df)
    
    # 1. Price change and rolling standard deviation
    delta_p = np.zeros(n)
    delta_p[1:] = np.diff(close)
    
    s = pd.Series(delta_p).rolling(window=vol_len, min_periods=1).std(ddof=1).fillna(0.0).values
    s_avg = pd.Series(s).rolling(window=vol_len, min_periods=1).mean().fillna(0.0).values
    
    s_min = s_avg * 0.25
    s_max = s_avg * 1.75
    vol_range = s_max - s_min
    
    # 2. Adaptive length interpolation
    adaptive_len = np.full(n, float(ma_max))
    valid_vol = vol_range > 0.0
    
    below_min = valid_vol & (s <= s_min)
    above_max = valid_vol & (s >= s_max)
    in_between = valid_vol & (~below_min) & (~above_max)
    
    adaptive_len[below_min] = float(ma_max)
    adaptive_len[above_max] = float(ma_min)
    adaptive_len[in_between] = ma_max - (ma_max - ma_min) * (s[in_between] - s_min[in_between]) / vol_range[in_between]
    
    alpha = 2.0 / (adaptive_len + 1.0)
    
    # 3. Recursive Adaptive MA
    adaptive_ma = np.zeros(n)
    adaptive_ma[0] = close[0]
    for t in range(1, n):
        adaptive_ma[t] = adaptive_ma[t-1] + alpha[t] * (close[t] - adaptive_ma[t-1])
        
    # 4. Ehlers Distance-Weighted Smoothing
    trend_ma = np.zeros(n)
    for t in range(n):
        num = 0.0
        denom = 0.0
        for i in range(ehlers_len):
            idx_curr = max(0, t - i)
            idx_mom = max(0, t - i - ehlers_mom)
            w = abs(adaptive_ma[idx_curr] - adaptive_ma[idx_mom])
            num += w * adaptive_ma[idx_curr]
            denom += w
        trend_ma[t] = (num / denom) if denom != 0.0 else adaptive_ma[t]
        
    # 5. Deviation & Nearest-Rank Percentile Bands
    deviation = np.abs(close - trend_ma)
    pct_dist = np.full(n, np.nan)
    for t in range(n):
        if t >= pct_len - 1:
            window = deviation[t - pct_len + 1 : t + 1]
            pct_dist[t] = np.percentile(window, pct_level, method='nearest')
        else:
            pct_dist[t] = np.percentile(deviation[: t + 1], pct_level, method='nearest') if t > 0 else deviation[0]
            
    upper_band = trend_ma + pct_dist * upper_mult
    lower_band = trend_ma - pct_dist * lower_mult
    
    # 6. Regime State Machine
    sq = np.zeros(n, dtype=int)
    curr_sq = 0
    for t in range(n):
        if close[t] > upper_band[t]:
            curr_sq = 1
        elif close[t] < lower_band[t]:
            curr_sq = -1
        sq[t] = curr_sq
        
    df_res = df.copy()
    df_res['AdaptiveLen'] = adaptive_len
    df_res['AdaptiveMA'] = adaptive_ma
    df_res['TrendMA'] = trend_ma
    df_res['UpperBand'] = upper_band
    df_res['LowerBand'] = lower_band
    df_res['SQ'] = sq
    df_res['BarColor'] = np.where(sq == 1, 'GREEN', 'PURPLE')
    return df_res


def backtest_plan_b_1x(df_calc, start_date='2023-01-01', end_date='2026-10-08',
                       exit_mode='dual_stage_buffered', pos_boost=1.0,
                       exec_timing='next_open', exit_weight=0.6, cost_rt=0.0):
    """
    cost_rt: round-trip trading cost as a fraction (e.g. 0.003 = 0.3%) covering commission,
    tax and slippage. Half is charged on the entry day and half on the exit day, scaled by
    the position size; trade returns in the ledger are net of it. Buy & Hold is left gross.
    Executes Plan B (1.0x Pure Spot):
      - Entry: Purple bar drops below LowerBand, then 1st Purple bar closes above LowerBand.
      - Exit: If reached UpperBand (Green bull market), exit when Close < (TrendMA * exit_weight + LowerBand * (1 - exit_weight)).
              If not reached UpperBand (still bottom stage), exit when Close < LowerBand.
      - 100% Spot, 1.0x position, zero leverage.
    """
    dates = df_calc.index
    closes = df_calc['Close'].values
    opens = df_calc['Open'].values
    lowers = df_calc['LowerBand'].values
    uppers = df_calc['UpperBand'].values
    trend_mas = df_calc['TrendMA'].values
    colors = df_calc['BarColor'].values
    sq = df_calc['SQ'].values
    n = len(df_calc)
    
    mask = (dates >= start_date) & (dates <= end_date)
    start_idx = np.where(mask)[0][0]
    end_idx = np.where(mask)[0][-1]
    
    buy_signals = np.zeros(n, dtype=bool)
    sell_signals = np.zeros(n, dtype=bool)
    
    had_breakdown = False
    in_pos = False
    reached_upper = False
    
    for t in range(n):
        c = closes[t]
        lb = lowers[t]
        ub = uppers[t]
        tma = trend_mas[t]
        col = colors[t]
        
        if not in_pos:
            if col == 'PURPLE' and c < lb:
                had_breakdown = True
            if had_breakdown and col == 'PURPLE' and c > lb:
                buy_signals[t] = True
                in_pos = True
                had_breakdown = False
                reached_upper = False
        else:
            if c > ub:
                reached_upper = True
                
            is_exit = False
            if exit_mode == 'dual_stage_buffered':
                if reached_upper:
                    target_floor = tma * exit_weight + lb * (1.0 - exit_weight)
                    if c < target_floor:
                        is_exit = True
                else:
                    if c < lb:
                        is_exit = True
            elif exit_mode == 'lower_band_buffer':
                # Plan A with buffer
                if c < lb * 0.985:
                    is_exit = True
            else: # raw lower band
                if c < lb:
                    is_exit = True
                    
            if is_exit:
                sell_signals[t] = True
                in_pos = False
                had_breakdown = True
                
    # Start flat: no position until the strategy itself fires a buy signal on or after the
    # bar before start_date (executed at the next open). A position the signal state machine
    # already held during the warm-up period is NOT inherited, so there is no start-state bias.
    half_cost = cost_rt / 2.0
    curr_pos = 0.0
    entry_price = 0.0
    entry_date = None
    
    trades = []
    daily_strat_ret = []
    daily_equity = [1.0]
    
    for i in range(start_idx, end_idx + 1):
        cur_date = dates[i]
        prev_close = closes[i-1]
        close_p = closes[i]
        open_p = opens[i]
        
        active_leverage = pos_boost if sq[i-1] == 1 else 1.0
        
        sig_b = buy_signals[i-1]
        sig_s = sell_signals[i-1]
        day_pnl = 0.0
        
        target_pos = curr_pos
        if sig_b:
            target_pos = 1.0
        elif sig_s:
            target_pos = 0.0
            
        if target_pos != curr_pos:
            if curr_pos == 1.0:
                ret_overnight = (open_p - prev_close) / prev_close * active_leverage
                day_pnl += ret_overnight - half_cost * active_leverage
                t_ret = (open_p - entry_price) / entry_price - cost_rt
                trades.append({
                    'type': 'LONG',
                    'entry_date': entry_date, 'entry_price': entry_price,
                    'exit_date': cur_date, 'exit_price': open_p,
                    'return': t_ret, 'bars': (cur_date - entry_date).days,
                    'open_pos': False
                })
            if target_pos == 1.0:
                entry_price = open_p
                entry_date = cur_date
                ret_intraday = (close_p - open_p) / open_p * active_leverage
                day_pnl += ret_intraday - half_cost * active_leverage
            else:
                entry_price = 0.0
                entry_date = None
            curr_pos = target_pos
        else:
            if curr_pos == 1.0:
                day_pnl += (close_p - prev_close) / prev_close * active_leverage
                
        daily_strat_ret.append(day_pnl)
        daily_equity.append(daily_equity[-1] * (1.0 + day_pnl))
        
    if curr_pos == 1.0 and entry_date is not None:
        last_close = closes[end_idx]
        t_ret = (last_close - entry_price) / entry_price - half_cost  # exit cost not yet paid
        trades.append({
            'type': 'LONG',
            'entry_date': entry_date, 'entry_price': entry_price,
            'exit_date': dates[end_idx], 'exit_price': last_close,
            'return': t_ret, 'bars': (dates[end_idx] - entry_date).days,
            'open_pos': True
        })
        
    cum_strat = np.array(daily_equity[1:])
    strat_ret = np.array(daily_strat_ret)
    
    bnh_base = closes[start_idx - 1]
    bnh_prices = closes[start_idx:end_idx + 1]
    cum_mkt = bnh_prices / bnh_base
    mkt_ret = np.diff(np.concatenate([[bnh_base], bnh_prices])) / np.concatenate([[bnh_base], bnh_prices[:-1]])
    
    tot_strat = (cum_strat[-1] - 1.0) * 100.0
    tot_mkt = (cum_mkt[-1] - 1.0) * 100.0
    excess_ret = tot_strat - tot_mkt  # simple total-return difference (not alpha)
    
    cummax_s = np.maximum.accumulate(cum_strat)
    dd_s = (cum_strat - cummax_s) / cummax_s * 100.0
    max_dd_s = np.min(dd_s)
    
    cummax_m = np.maximum.accumulate(cum_mkt)
    dd_m = (cum_mkt - cummax_m) / cummax_m * 100.0
    max_dd_m = np.min(dd_m)
    
    years = (dates[end_idx] - dates[start_idx]).days / 365.25
    cagr_s = ((cum_strat[-1]) ** (1.0 / years) - 1.0) * 100.0
    cagr_m = ((cum_mkt[-1]) ** (1.0 / years) - 1.0) * 100.0
    
    tdf = pd.DataFrame(trades)
    win_rate = (tdf['return'] > 0).mean() * 100.0 if len(tdf) > 0 else 0
    pos_rets = tdf[tdf['return'] > 0]['return']
    neg_rets = tdf[tdf['return'] < 0]['return']
    pf = pos_rets.sum() / abs(neg_rets.sum()) if len(neg_rets) > 0 and neg_rets.sum() != 0 else 999.0
    avg_win = pos_rets.mean() * 100.0 if len(pos_rets) > 0 else 0.0
    avg_loss = neg_rets.mean() * 100.0 if len(neg_rets) > 0 else 0.0
    win_loss = abs(avg_win / avg_loss) if avg_loss != 0 else 999.0
    
    sharpe_s = (np.mean(strat_ret) / (np.std(strat_ret) + 1e-8)) * np.sqrt(252)
    downside_s = strat_ret[strat_ret < 0]
    sortino_s = (np.mean(strat_ret) * 252) / (np.std(downside_s) * np.sqrt(252)) if len(downside_s) > 0 else 0
    # Calmar = CAGR / |MaxDD| (industry standard; total return / MDD inflates with period length)
    calmar_s = cagr_s / abs(max_dd_s) if max_dd_s != 0 else 0.0
    calmar_m = cagr_m / abs(max_dd_m) if max_dd_m != 0 else 0.0

    # Jensen's alpha: OLS of daily strategy returns on daily market returns (rf = 0),
    # intercept annualised x252. beta = market exposure, alpha_t = t-stat of the intercept.
    n = min(len(strat_ret), len(mkt_ret))
    y, x = strat_ret[-n:], mkt_ret[-n:]
    X = np.column_stack([np.ones(n), x])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    sigma2 = resid @ resid / max(n - 2, 1)
    se = np.sqrt(np.diag(sigma2 * np.linalg.inv(X.T @ X)))
    alpha = coef[0] * 252 * 100.0
    beta = coef[1]
    alpha_t = coef[0] / se[0] if se[0] > 0 else 0.0
    
    return {
        'tot_strat': tot_strat,
        'tot_mkt': tot_mkt,
        'alpha': alpha,
        'alpha_t': alpha_t,
        'beta': beta,
        'excess_ret': excess_ret,
        'cagr_s': cagr_s,
        'cagr_m': cagr_m,
        'max_dd_s': max_dd_s,
        'max_dd_m': max_dd_m,
        'win_rate': win_rate,
        'profit_factor': pf,
        'win_loss': win_loss,
        'sharpe_s': sharpe_s,
        'sortino_s': sortino_s,
        'calmar_s': calmar_s,
        'calmar_m': calmar_m,
        'trades_count': len(tdf),
        'cost_rt': cost_rt,
        'trades': tdf,
        'cum_strat': cum_strat,
        'cum_mkt': cum_mkt,
        'dd_s': dd_s,
        'dd_m': dd_m,
        'dates': dates[start_idx:end_idx + 1]
    }


MODES = {
    'plan_b_1x':  {'exit_mode': 'dual_stage_buffered', 'pos_boost': 1.0, 'label': '方案 B 破底翻',
                   'en': 'Plan B 1.0x', 'leverage': '1.0x 純現貨', 'two_stage': True},
    'plan_a_1x':  {'exit_mode': 'lower_band_buffer', 'pos_boost': 1.0, 'label': '方案 A 破底翻',
                   'en': 'Plan A 1.0x', 'leverage': '1.0x 純現貨', 'two_stage': False},
    'plan_b_12x': {'exit_mode': 'dual_stage_buffered', 'pos_boost': 1.2, 'label': '方案 B 微槓桿',
                   'en': 'Plan B 1.2x', 'leverage': '綠色多頭區 1.2x、其餘 1.0x', 'two_stage': True},
}


def replay_exit_floor(df_calc, exit_mode='dual_stage_buffered', exit_weight=0.6, first_bar=0):
    """
    Re-runs the backtest's signal state machine to recover, for every bar, the exit floor
    that was active while a position was held (NaN when flat) and its stage (0 flat, 1, 2).
    Must mirror backtest_plan_b_1x's entry/exit rules exactly. Positions whose entry signal
    fired before `first_bar` (the bar before the backtest start) are ignored, because the
    backtest starts flat and never inherits them.
    """
    c = df_calc['Close'].values
    lb = df_calc['LowerBand'].values
    ub = df_calc['UpperBand'].values
    tma = df_calc['TrendMA'].values
    col = df_calc['BarColor'].values
    n = len(df_calc)
    floor = np.full(n, np.nan)
    stage = np.zeros(n, dtype=int)
    had_breakdown = in_pos = reached_upper = False
    entry_t = -1
    episode = np.full(n, -1)  # bar index of the entry signal for each held bar
    for t in range(n):
        if not in_pos:
            if col[t] == 'PURPLE' and c[t] < lb[t]:
                had_breakdown = True
            if had_breakdown and col[t] == 'PURPLE' and c[t] > lb[t]:
                in_pos, had_breakdown, reached_upper = True, False, False
                entry_t = t
                episode[t] = t
                floor[t] = lb[t] * 0.985 if exit_mode == 'lower_band_buffer' else lb[t]
                stage[t] = 1
        else:
            if c[t] > ub[t]:
                reached_upper = True
            if exit_mode == 'dual_stage_buffered' and reached_upper:
                f = tma[t] * exit_weight + lb[t] * (1.0 - exit_weight)
            elif exit_mode == 'lower_band_buffer':
                f = lb[t] * 0.985
            else:
                f = lb[t]
            floor[t] = f
            episode[t] = entry_t
            stage[t] = 2 if (exit_mode == 'dual_stage_buffered' and reached_upper) else 1
            if c[t] < f:
                in_pos, had_breakdown = False, True
    # the backtest only holds positions entered on a signal at or after first_bar
    inherited = (episode >= 0) & (episode < first_bar)
    floor[inherited], stage[inherited] = np.nan, 0
    return floor, stage


def build_report_data(df_calc, res, symbol, start_date, end_date, mode, exit_weight=0.6):
    """Collects everything the HTML report needs into one JSON-serialisable dict."""
    cfg = MODES[mode]
    mask = (df_calc.index >= start_date) & (df_calc.index <= end_date)
    idx = np.where(mask)[0]
    floor, stage = replay_exit_floor(df_calc, cfg['exit_mode'], exit_weight, first_bar=idx[0] - 1)
    v = df_calc.iloc[idx]

    def r2(a):
        return [None if (x is None or not np.isfinite(x)) else round(float(x), 2) for x in np.asarray(a, dtype=float)]

    trades = [{
        'entry': pd.Timestamp(tr['entry_date']).strftime('%Y-%m-%d'), 'entryPx': round(float(tr['entry_price']), 2),
        'exit': pd.Timestamp(tr['exit_date']).strftime('%Y-%m-%d'), 'exitPx': round(float(tr['exit_price']), 2),
        'ret': round(float(tr['return']) * 100, 2), 'days': int(tr['bars']), 'open': bool(tr['open_pos']),
    } for _, tr in res['trades'].iterrows()]

    keys = ['tot_strat', 'tot_mkt', 'excess_ret', 'alpha', 'alpha_t', 'beta', 'cagr_s', 'cagr_m', 'max_dd_s', 'max_dd_m', 'calmar_s',
            'sharpe_s', 'sortino_s', 'win_rate', 'profit_factor', 'win_loss', 'trades_count']
    stats = {k: round(float(res[k]), 2) for k in keys}
    stats['bnh_calmar'] = round(float(res['calmar_m']), 2)

    if cfg['exit_mode'] == 'dual_stage_buffered':
        exit_rule = (f'收盤站上上軌之前，收盤跌破下軌就停損；站上上軌之後，出場線上移到 '
                     f'{exit_weight:g} × TrendMA + {1 - exit_weight:g} × 下軌。訊號在收盤確認，隔天開盤成交。')
    else:
        exit_rule = '收盤跌破「下軌 × 0.985」（下軌再往下 1.5% 的緩衝）就出場。訊號在收盤確認，隔天開盤成交。'

    last = v.iloc[-1]
    return {
        'symbol': symbol, 'start': start_date, 'end': end_date,
        'meta': {'symbol': symbol, 'mode': mode, 'modeLabel': cfg['label'], 'modeEn': cfg['en'],
                 'leverage': cfg['leverage'], 'twoStage': cfg['two_stage'],
                 'costPct': round(float(res['cost_rt']) * 100, 4),
                 'floorName': '下軌 −1.5%' if cfg['exit_mode'] == 'lower_band_buffer' else '下軌',
                 'exitRule': exit_rule,
                 'params': f'vol 12、Ehlers 9 / 12、百分位 40 根 75%、上軌 0.7、下軌 0.8、出場權重 {exit_weight:g}'},
        'dates': [d.strftime('%Y-%m-%d') for d in v.index],
        'ohlc': [[round(float(o), 2), round(float(c), 2), round(float(lo), 2), round(float(hi), 2)]
                 for o, c, lo, hi in zip(v['Open'], v['Close'], v['Low'], v['High'])],
        'trend': r2(v['TrendMA']), 'upper': r2(v['UpperBand']), 'lower': r2(v['LowerBand']),
        'floor': r2(floor[idx]), 'stage': stage[idx].tolist(), 'sq': v['SQ'].astype(int).tolist(),
        'equity': r2((res['cum_strat'] - 1) * 100), 'bnh': r2((res['cum_mkt'] - 1) * 100),
        'ddS': r2(res['dd_s']), 'ddM': r2(res['dd_m']),
        'trades': trades, 'stats': stats,
        'last': {'date': v.index[-1].strftime('%Y-%m-%d'), 'close': round(float(last['Close']), 2),
                 'trend': round(float(last['TrendMA']), 2), 'upper': round(float(last['UpperBand']), 2),
                 'lower': round(float(last['LowerBand']), 2), 'floor': r2([floor[idx[-1]]])[0],
                 'stage': int(stage[idx[-1]]), 'sq': int(last['SQ'])},
    }


def write_html_report(data, out_path):
    """Fills scripts/report_template.html with the report data and writes a self-contained HTML file."""
    tpl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'report_template.html')
    with open(tpl_path, encoding='utf-8') as f:
        tpl = f.read()
    m = data['meta']
    title = html.escape(f"{m['modeLabel']} {data['symbol']} 回測")
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    page = tpl.replace('__TITLE__', title).replace('/*__DATA__*/null', payload)
    if not page.lstrip().lower().startswith('<!doctype'):
        page = ('<!doctype html>\n<html lang="zh-Hant">\n<head>\n<meta charset="utf-8">\n'
                '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                '</head>\n<body>\n' + page + '\n</body>\n</html>\n')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(page)
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Adaptive Ehlers Percentile Reclaim (Plan B 1.0x) Engine")
    parser.add_argument("--symbol", type=str, default="^TWII", help="Ticker symbol (default: ^TWII)")
    parser.add_argument("--start", type=str, default="2023-01-01", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", type=str, default="2026-10-08", help="End date YYYY-MM-DD")
    parser.add_argument("--mode", type=str, default="plan_b_1x", choices=["plan_b_1x", "plan_a_1x", "plan_b_12x", "compare"],
                        help="Strategy mode: plan_b_1x (default), plan_a_1x, plan_b_12x, compare")
    parser.add_argument("--out", type=str, default=None,
                        help="Output HTML file path (default: <symbol>_ehlers_<mode>_<start>_<end>.html in the current directory)")
    parser.add_argument("--cost", type=float, default=0.3,
                        help="Round-trip trading cost in percent (commission + tax + slippage), default 0.3; 0 = gross")
    parser.add_argument("--no-html", action="store_true", help="Print the console summary only, skip the HTML report")
    args = parser.parse_args()
    
    print(f"Fetching {args.symbol} data with warmup...")
    # Warmup 1 year before start
    start_dt = pd.to_datetime(args.start)
    warmup_start = (start_dt - pd.DateOffset(years=1)).strftime('%Y-%m-%d')
    end_dt = (pd.to_datetime(args.end) + pd.DateOffset(days=5)).strftime('%Y-%m-%d')
    
    df = yf.download(args.symbol, start=warmup_start, end=end_dt, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
        
    df_calc = run_ehlers_percentile(df)
    
    # Run backtest
    cost_rt = args.cost / 100.0
    res_b_1x = backtest_plan_b_1x(df_calc, start_date=args.start, end_date=args.end, exit_mode='dual_stage_buffered', pos_boost=1.0, cost_rt=cost_rt)
    res_a_1x = backtest_plan_b_1x(df_calc, start_date=args.start, end_date=args.end, exit_mode='lower_band_buffer', pos_boost=1.0, cost_rt=cost_rt)
    res_b_12x = backtest_plan_b_1x(df_calc, start_date=args.start, end_date=args.end, exit_mode='dual_stage_buffered', pos_boost=1.20, cost_rt=cost_rt)
    
    print("=========================================================================")
    print(f"  ADAPTIVE EHLERS RECLAIM STRATEGY ENGINE — {args.symbol}")
    print(f"  Period: {args.start} ~ {args.end} | Round-trip cost: {args.cost:g}% (B&H gross)")
    print("=========================================================================")
    print(f"[Plan B (1.0x Pure Spot / Dual-Stage Exit)]")
    print(f"  Total Return: {res_b_1x['tot_strat']:+7.2f}% (B&H: {res_b_1x['tot_mkt']:+7.2f}%) | Excess: {res_b_1x['excess_ret']:+7.2f}%")
    print(f"  Alpha (ann.): {res_b_1x['alpha']:+7.2f}% (t = {res_b_1x['alpha_t']:.2f}) | Beta: {res_b_1x['beta']:.2f}")
    print(f"  CAGR:         {res_b_1x['cagr_s']:+7.2f}% (B&H: {res_b_1x['cagr_m']:+7.2f}%)")
    print(f"  Max Drawdown: {res_b_1x['max_dd_s']:7.2f}% (B&H: {res_b_1x['max_dd_m']:7.2f}%) | Calmar: {res_b_1x['calmar_s']:.2f}")
    print(f"  Sharpe Ratio: {res_b_1x['sharpe_s']:7.2f}  | Sortino: {res_b_1x['sortino_s']:.2f}")
    print(f"  Win Rate:     {res_b_1x['win_rate']:7.1f}% | Profit Factor: {res_b_1x['profit_factor']:.2f} | Payoff: {res_b_1x['win_loss']:.2f}")
    print(f"  Trades Count: {res_b_1x['trades_count']}")
    print("-------------------------------------------------------------------------")
    print(f"[Comparison Matrix]")
    print(f"  Plan B (1.0x Spot)  : Return {res_b_1x['tot_strat']:+7.2f}% | MaxDD {res_b_1x['max_dd_s']:6.2f}% | Calmar {res_b_1x['calmar_s']:.2f}")
    print(f"  Plan A (1.0x Buffer): Return {res_a_1x['tot_strat']:+7.2f}% | MaxDD {res_a_1x['max_dd_s']:6.2f}% | Calmar {res_a_1x['calmar_s']:.2f}")
    print(f"  Plan B (1.2x Boost) : Return {res_b_12x['tot_strat']:+7.2f}% | MaxDD {res_b_12x['max_dd_s']:6.2f}% | Calmar {res_b_12x['calmar_s']:.2f}")
    print(f"  Buy & Hold Benchmark: Return {res_b_1x['tot_mkt']:+7.2f}% | MaxDD {res_b_1x['max_dd_m']:6.2f}% | Calmar {res_b_1x['calmar_m']:.2f}")
    print("=========================================================================")

    if not args.no_html:
        report_mode = 'plan_b_1x' if args.mode == 'compare' else args.mode
        res_report = {'plan_b_1x': res_b_1x, 'plan_a_1x': res_a_1x, 'plan_b_12x': res_b_12x}[report_mode]
        out = args.out or "{}_ehlers_{}_{}_{}.html".format(
            "".join(ch if ch.isalnum() else "_" for ch in args.symbol).strip("_"),
            report_mode, args.start.replace("-", ""), args.end.replace("-", ""))
        data = build_report_data(df_calc, res_report, args.symbol, args.start, args.end, report_mode)
        path = write_html_report(data, out)
        last = data['last']
        state = (f"HOLDING, exit floor {last['floor']:,.2f} (stage {last['stage']})"
                 if last['floor'] is not None else "FLAT")
        print(f"[{MODES[report_mode]['en']}] Last bar {last['date']} close {last['close']:,.2f} -> {state}")
        print(f"HTML report written: {os.path.abspath(path)}")


if __name__ == '__main__':
    main()
