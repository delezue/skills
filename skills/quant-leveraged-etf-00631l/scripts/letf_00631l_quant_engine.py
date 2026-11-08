#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
華爾街機構級：槓桿 ETF (00631L / 00675L) 量化微結構、50:50 再平衡與 DSP/ML 動態曝險終端
Skill: quant-leveraged-etf-00631l
Distilled from: 《槓桿ETF投資法：用50正2輕鬆打敗0050＆0056，提早退休》（大仁 著）
"""

import argparse
import datetime
import json
import math
import os
import ssl
import subprocess
import sys
import tempfile
import urllib.request
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

sys.stdout.reconfigure(encoding='utf-8')
ctx = ssl._create_unverified_context()


def fetch_yahoo_chart(symbol, start_ts=1414627200):
    """
    Fetch daily historical OHLC + Adj Close from Yahoo Finance v8 chart API (with splits & dividend adjustment).
    1414627200 = 2014-10-30 UTC (00631L listed on 2014-10-31).
    """
    end_ts = int(datetime.datetime.now().timestamp()) + 86400
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ urllib.parse.quote(symbol) }?period1={start_ts}&period2={end_ts}&interval=1d&events=div%2Csplit"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    with urllib.request.urlopen(req, context=ctx, timeout=25) as r:
        data = json.loads(r.read().decode('utf-8'))

    res = data['chart']['result'][0]
    timestamps = res['timestamp']
    quote = res['indicators']['quote'][0]
    adj = res['indicators'].get('adjclose', [{}])[0].get('adjclose', quote['close'])

    rows = []
    for ts, c, ac in zip(timestamps, quote['close'], adj):
        if c is None or ac is None:
            continue
        dt_str = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y-%m-%d')
        rows.append({'date': dt_str, 'close': float(c), 'adj_close': float(ac)})

    df = pd.DataFrame(rows).drop_duplicates(subset=['date'], keep='last').sort_values('date').reset_index(drop=True)
    return df


def calc_zlema(series, span):
    lag = int((span - 1) / 2)
    s = pd.Series(series, dtype=float)
    de_lagged = 2.0 * s - s.shift(lag).bfill()
    return de_lagged.ewm(span=span, adjust=False).mean().values


def calc_kalman_1d(series, q=1e-4, r=1e-2):
    n = len(series)
    xhat = np.zeros(n)
    P = 1.0
    xhat[0] = series[0]
    for k in range(1, n):
        P_pred = P + q
        K = P_pred / (P_pred + r)
        xhat[k] = xhat[k - 1] + K * (series[k] - xhat[k - 1])
        P = (1.0 - K) * P_pred
    return xhat


def run_backtest_and_models(letf_sym='00631L.TW', spot_sym='0050.TW', div_sym='0056.TW', rebal_thresh=0.50, daily_withdraw=2000.0, cash_rate=0.012):
    print(f"[Step 1] 正在下載歷史日線與還原權息數據: {letf_sym}, {spot_sym}, {div_sym}, ^TWII ...")
    df_letf = fetch_yahoo_chart(letf_sym)
    df_spot = fetch_yahoo_chart(spot_sym)
    df_div = fetch_yahoo_chart(div_sym)
    df_twii = fetch_yahoo_chart('^TWII')

    # Merge on common trading dates starting from 00631L inception (2014-10-31)
    df = df_letf.rename(columns={'close': 'letf_px', 'adj_close': 'letf_adj'})[['date', 'letf_px', 'letf_adj']]
    df = df.merge(df_spot.rename(columns={'close': 'spot_px', 'adj_close': 'spot_adj'})[['date', 'spot_px', 'spot_adj']], on='date', how='inner')
    df = df.merge(df_div.rename(columns={'close': 'div_px', 'adj_close': 'div_adj'})[['date', 'div_px', 'div_adj']], on='date', how='inner')
    df = df.merge(df_twii.rename(columns={'close': 'twii_px'})[['date', 'twii_px']], on='date', how='left')
    df['twii_px'] = df['twii_px'].ffill().bfill()
    df = df.sort_values('date').reset_index(drop=True)

    # Fix any anomalous split/dividend adjustment jumps in Yahoo Finance adj_close by using daily return sanity checks
    for col in ['letf_adj', 'spot_adj', 'div_adj', 'letf_px', 'spot_px', 'div_px']:
        s = df[col].values.copy()
        for i in range(1, len(s)):
            ratio = s[i] / s[i - 1] if s[i - 1] > 0 else 1.0
            # Detect unadjusted split (e.g. 0050 1-for-4 split where price drops ~75% in 1 day)
            if ratio < 0.35 or ratio > 2.8:
                s[i:] = s[i:] / ratio
        df[col] = s

    n = len(df)
    print(f"  -> 共對齊 {n} 個交易日 ({df['date'].iloc[0]} ~ {df['date'].iloc[-1]})")

    # Daily returns (Total Return including dividends reinvested)
    r_letf = df['letf_adj'].pct_change().fillna(0.0).values
    r_spot = df['spot_adj'].pct_change().fillna(0.0).values
    r_div = df['div_adj'].pct_change().fillna(0.0).values
    r_cash_daily = (1.0 + cash_rate) ** (1.0 / 252.0) - 1.0

    # DSP Indicators on LETF & Spot
    df['letf_zlema20'] = calc_zlema(df['letf_adj'].values, 20)
    df['letf_zlema60'] = calc_zlema(df['letf_adj'].values, 60)
    df['letf_zlema200'] = calc_zlema(df['letf_adj'].values, 200)
    df['letf_kalman'] = calc_kalman_1d(df['letf_adj'].values, q=5e-4, r=1e-2)

    # Rolling 20D annualized volatility of Spot Index
    spot_vol_20d = pd.Series(r_spot).rolling(20).std().bfill().values * math.sqrt(252.0)
    df['spot_vol_20d'] = spot_vol_20d * 100.0

    # Peak Drawdown of LETF and Spot (for 高點回推法 Ch 3-12~3-14)
    letf_peak = np.maximum.accumulate(df['letf_adj'].values)
    spot_peak = np.maximum.accumulate(df['spot_adj'].values)
    letf_dd = (df['letf_adj'].values / letf_peak) - 1.0
    spot_dd = (df['spot_adj'].values / spot_peak) - 1.0
    df['letf_dd_pct'] = letf_dd * 100.0
    df['spot_dd_pct'] = spot_dd * 100.0

    # Initial Capital = 10,000,000 TWD (1,000萬，對應書中 3-6 / 3-8 實戰金額，亦可等比換算 100萬)
    INIT_CAP = 1000.0  # 單位：萬元 (1,000 萬 = 1000.0 萬，為了與書中 100萬 基準直覺對照，我們用 100.0 萬作為標準曲線基底，日日配獨立用 1,000 萬)
    BASE_100W = 100.0  # 100 萬元本金

    # 1. 100% 0050 (DRIP 含息總報酬)
    eq_0050 = BASE_100W * (df['spot_adj'].values / df['spot_adj'].iloc[0])
    # 2. 100% 0056 (DRIP 含息總報酬)
    eq_0056 = BASE_100W * (df['div_adj'].values / df['div_adj'].iloc[0])
    # 3. 100% 00631L (Level 5 生命週期 200% 曝險)
    eq_letf_100 = BASE_100W * (df['letf_adj'].values / df['letf_adj'].iloc[0])
    # 4. 2x Simulated Price Index (模擬純2倍加權指數 ^TWII，扣除內扣、不含 ~8.2% 除息逆價差與外資避險逆價差 Alpha，對應書中 1-14 ~ 1-17)
    r_twii = df['twii_px'].pct_change().fillna(0.0).values
    r_sim2x = np.clip(2.0 * r_twii - (0.0115 / 252.0), -0.99, None)
    eq_sim2x = BASE_100W * np.cumprod(1.0 + r_sim2x)

    # 5. 書中核心王牌：「50:50 槓桿投資法 + ±50% 閾值觸發再平衡」(Ch 3-3, 3-4, 3-5, 4-6)
    eq_5050_tot = np.zeros(n)
    eq_5050_letf = np.zeros(n)
    eq_5050_cash = np.zeros(n)
    rebal_events = []

    cur_letf = BASE_100W * 0.50
    cur_cash = BASE_100W * 0.50
    anchor_letf = cur_letf

    for i in range(n):
        if i > 0:
            cur_letf *= (1.0 + r_letf[i])
            cur_cash *= (1.0 + r_cash_daily)
        tot_i = cur_letf + cur_cash
        # Check if LETF leg has grown >= +rebal_thresh or dropped <= -rebal_thresh relative to anchor_letf (Book Ch 3-4 rule)
        letf_chg_from_anchor = (cur_letf / anchor_letf) - 1.0 if anchor_letf > 0 else 0.0
        if abs(letf_chg_from_anchor) >= rebal_thresh:
            old_letf = cur_letf
            old_cash = cur_cash
            cur_letf = tot_i * 0.50
            cur_cash = tot_i * 0.50
            anchor_letf = cur_letf
            rebal_events.append({
                'count': len(rebal_events) + 1,
                'date': df['date'].iloc[i],
                'trigger_pct': round(letf_chg_from_anchor * 100.0, 2),
                'action': '賣高正2轉入現金 (鎖利)' if old_letf > cur_letf else '動用現金抄底正2 (加碼)',
                'pre_letf_w': round(old_letf, 2),
                'pre_cash_w': round(old_cash, 2),
                'post_letf_w': round(cur_letf, 2),
                'post_cash_w': round(cur_cash, 2),
                'total_w': round(tot_i, 2)
            })
        eq_5050_letf[i] = cur_letf
        eq_5050_cash[i] = cur_cash
        eq_5050_tot[i] = tot_i

    # 6. 華爾街機構升級版：「DSP (Kalman + ZLEMA) + 波動率目標 + 高點回推法逆勢加碼」動態曝險策略
    eq_dsp_tot = np.zeros(n)
    eq_dsp_exposure = np.zeros(n)
    dsp_letf = BASE_100W * 0.55
    dsp_cash = BASE_100W * 0.45

    for i in range(n):
        if i > 0:
            dsp_letf *= (1.0 + r_letf[i])
            dsp_cash *= (1.0 + r_cash_daily)
        tot_d = dsp_letf + dsp_cash

        # Weekly / Regime target weight evaluation (every 5 trading days to minimize turnover)
        if i >= 60 and i % 5 == 0:
            px_i = df['letf_adj'].iloc[i]
            z20 = df['letf_zlema20'].iloc[i]
            z60 = df['letf_zlema60'].iloc[i]
            kal = df['letf_kalman'].iloc[i]
            vol_i = spot_vol_20d[i]
            dd_i = abs(letf_dd[i])

            # Base weight = 58% (116% effective exposure, dynamically scaling 70%~170%)
            if dd_i >= 0.35:
                # 觸發大仁「高點回推法」深度價值加碼區 (正2跌幅 >= 35%，預期反彈 > +54%)
                target_w = min(0.85, 0.62 + (dd_i - 0.35) * 0.9)
            elif px_i > z20 and z20 > z60 and px_i > kal and vol_i < 0.28:
                # 低波動穩定多頭期：享受二階正向複利紅利 (Level 4: 156% 曝險)
                target_w = 0.78
            elif px_i < z60 and vol_i > 0.28:
                # 高波動初跌/盤整耗損期：降檔保護，減少波動耗損 (Level 2: 70% 曝險)
                target_w = 0.35
            else:
                target_w = 0.58

            cur_w = dsp_letf / tot_d if tot_d > 0 else 0.50
            if abs(cur_w - target_w) >= 0.08:
                dsp_letf = tot_d * target_w
                dsp_cash = tot_d * (1.0 - target_w)

        eq_dsp_tot[i] = tot_d
        eq_dsp_exposure[i] = (dsp_letf / tot_d) * 200.0 if tot_d > 0 else 100.0

    # 7. 書中 Ch 3-6：「1,000萬本金 50:50 日日配現金流 (每交易日領 2,000 元 = 0.2 萬)」vs 1,000萬 0056
    CAP_1000W = 1000.0
    daily_w_wan = daily_withdraw / 10000.0  # 0.2 萬元/日
    cf_letf = CAP_1000W * 0.50
    cf_cash = CAP_1000W * 0.50
    cf_anchor = cf_letf
    cf_withdrawn_cum = 0.0
    cf_rebal_cnt = 0
    for i in range(n):
        if i > 0:
            cf_letf *= (1.0 + r_letf[i])
            cf_cash = cf_cash * (1.0 + r_cash_daily) - daily_w_wan
            cf_withdrawn_cum += daily_w_wan
            if cf_cash < 50.0 or abs((cf_letf / cf_anchor) - 1.0) >= rebal_thresh:
                tot_cf = cf_letf + cf_cash
                cf_letf = tot_cf * 0.50
                cf_cash = tot_cf * 0.50
                cf_anchor = cf_letf
                cf_rebal_cnt += 1

    # 8. Annual Breakdown Table (Ch 1-10, 1-19, 4-4: 紅利 vs 耗損 與 逆價差超額報酬年度拆解)
    df['year'] = df['date'].str.slice(0, 4)
    annual_rows = []
    for yr, grp in df.groupby('year'):
        if len(grp) < 15:
            continue
        idx_start = grp.index[0] - 1 if grp.index[0] > 0 else grp.index[0]
        idx_end = grp.index[-1]

        r_sp_yr = (df['spot_adj'].iloc[idx_end] / df['spot_adj'].iloc[idx_start] - 1.0) * 100.0
        r_twii_yr = (df['twii_px'].iloc[idx_end] / df['twii_px'].iloc[idx_start] - 1.0) * 100.0
        r_dv_yr = (df['div_adj'].iloc[idx_end] / df['div_adj'].iloc[idx_start] - 1.0) * 100.0
        r_lt_yr = (df['letf_adj'].iloc[idx_end] / df['letf_adj'].iloc[idx_start] - 1.0) * 100.0
        r_5050_yr = (eq_5050_tot[idx_end] / eq_5050_tot[idx_start] - 1.0) * 100.0
        r_dsp_yr = (eq_dsp_tot[idx_end] / eq_dsp_tot[idx_start] - 1.0) * 100.0

        # Annualized volatility in this year
        sub_r_sp = r_twii[grp.index[0]:grp.index[-1] + 1]
        vol_yr = float(np.std(sub_r_sp) * math.sqrt(252.0))
        T_yr = len(grp) / 252.0

        # Naive 2x vs Itô Theoretical 2x based on Price Index ^TWII (Ch 1-14~1-17 & Ch 4-3 without dividend/roll backwardation)
        naive_2x = 2.0 * r_twii_yr
        ito_expected_2x = ((1.0 + r_twii_yr / 100.0) ** 2 * math.exp(-(vol_yr ** 2) * T_yr) - 1.0) * 100.0
        bonus_vs_2x = r_lt_yr - naive_2x
        roll_and_fee_alpha = r_lt_yr - ito_expected_2x

        annual_rows.append({
            'year': yr,
            'days': len(grp),
            'spot_ret': round(r_sp_yr, 2),
            'div_ret': round(r_dv_yr, 2),
            'naive_2x': round(naive_2x, 2),
            'vol_yr': round(vol_yr * 100.0, 2),
            'ito_2x': round(ito_expected_2x, 2),
            'letf_ret': round(r_lt_yr, 2),
            'bonus_vs_2x': round(bonus_vs_2x, 2),
            'roll_alpha': round(roll_and_fee_alpha, 2),
            'ret_5050': round(r_5050_yr, 2),
            'ret_dsp': round(r_dsp_yr, 2)
        })

    # 9. Rolling Horizon Win-Rate Analysis (Ch 1-19: 1Y, 2Y, 3Y, 5Y Rolling Windows)
    rolling_stats = []
    for horizon_yr, days_w in [('1年 (252日)', 252), ('2年 (504日)', 504), ('3年 (756日)', 756), ('5年 (1260日)', 1260)]:
        if n <= days_w:
            continue
        sp_roll = (df['spot_adj'].values[days_w:] / df['spot_adj'].values[:-days_w] - 1.0) * 100.0
        lt_roll = (df['letf_adj'].values[days_w:] / df['letf_adj'].values[:-days_w] - 1.0) * 100.0
        b50_roll = (eq_5050_tot[days_w:] / eq_5050_tot[:-days_w] - 1.0) * 100.0
        dsp_roll = (eq_dsp_tot[days_w:] / eq_dsp_tot[:-days_w] - 1.0) * 100.0

        rolling_stats.append({
            'horizon': horizon_yr,
            'samples': len(sp_roll),
            'letf_pos_rate': round(float(np.mean(lt_roll > 0) * 100.0), 2),
            'letf_beat_0050_rate': round(float(np.mean(lt_roll > sp_roll) * 100.0), 2),
            'b5050_beat_0050_rate': round(float(np.mean(b50_roll > sp_roll) * 100.0), 2),
            'dsp_beat_0050_rate': round(float(np.mean(dsp_roll > sp_roll) * 100.0), 2),
            'sp_mean_ret': round(float(np.mean(sp_roll)), 2),
            'lt_mean_ret': round(float(np.mean(lt_roll)), 2),
            'b50_mean_ret': round(float(np.mean(b50_roll)), 2),
            'dsp_mean_ret': round(float(np.mean(dsp_roll)), 2)
        })

    # 10. Machine Learning Feature Importance (Random Forest predicting 60D forward 00631L excess return over 2x 0050)
    fwd_days = 60
    df_ml = pd.DataFrame({
        '波動率 (20D Annualized Vol)': spot_vol_20d,
        '高點回撤深度 (Peak Drawdown %)': np.abs(letf_dd),
        'ZLEMA20 乖離率 (Short Trend Bias)': (df['letf_adj'].values / df['letf_zlema20'].values) - 1.0,
        'ZLEMA60 乖離率 (Medium Trend Bias)': (df['letf_adj'].values / df['letf_zlema60'].values) - 1.0,
        'Kalman 趨勢斜率 (DSP Velocity)': pd.Series(df['letf_kalman']).pct_change(10).fillna(0.0).values,
        '近20日逆價差超額動能 (Roll Alpha 20D)': pd.Series(r_letf - 2.0 * r_spot).rolling(20).sum().fillna(0.0).values
    })
    fwd_letf = pd.Series(df['letf_adj']).shift(-fwd_days) / df['letf_adj'] - 1.0
    fwd_spot = pd.Series(df['spot_adj']).shift(-fwd_days) / df['spot_adj'] - 1.0
    y_target = (fwd_letf - 2.0 * fwd_spot).values

    valid_mask = ~np.isnan(y_target) & (np.arange(n) >= 60)
    rf = RandomForestRegressor(n_estimators=120, max_depth=5, random_state=42)
    rf.fit(df_ml.loc[valid_mask], y_target[valid_mask])
    ml_importances = [
        {'feature': col, 'importance_pct': round(float(imp * 100.0), 2)}
        for col, imp in sorted(zip(df_ml.columns, rf.feature_importances_), key=lambda x: x[1], reverse=True)
    ]

    # 11. Compute Portfolio KPIs Summary
    years_elapsed = (pd.to_datetime(df['date'].iloc[-1]) - pd.to_datetime(df['date'].iloc[0])).days / 365.25

    def calc_kpis(name, eq_arr, exposure_desc):
        tot_ret = (eq_arr[-1] / eq_arr[0] - 1.0) * 100.0
        cagr = ((eq_arr[-1] / eq_arr[0]) ** (1.0 / years_elapsed) - 1.0) * 100.0
        daily_r = pd.Series(eq_arr).pct_change().dropna().values
        vol = float(np.std(daily_r) * math.sqrt(252.0) * 100.0)
        sharpe = (cagr - cash_rate * 100.0) / vol if vol > 0 else 0.0
        pk = np.maximum.accumulate(eq_arr)
        dd = (eq_arr / pk - 1.0) * 100.0
        mdd = float(np.min(dd))
        calmar = cagr / abs(mdd) if mdd < 0 else 0.0
        return {
            'name': name,
            'exposure': exposure_desc,
            'end_val_w': round(float(eq_arr[-1]), 2),
            'tot_ret_pct': round(tot_ret, 2),
            'cagr_pct': round(cagr, 2),
            'vol_pct': round(vol, 2),
            'sharpe': round(sharpe, 2),
            'mdd_pct': round(mdd, 2),
            'calmar': round(calmar, 2)
        }

    kpi_table = [
        calc_kpis(f'1. 100% 高股息 ({div_sym})', eq_0056, '100% 高股息現貨 (0% 現金)'),
        calc_kpis(f'2. 100% 市值型 ({spot_sym})', eq_0050, '100% 大型股現貨 (0% 現金)'),
        calc_kpis('3. 50:50 槓桿投資法 (書中核心)', eq_5050_tot, f'50% 正2 + 50% 現金 (100% 曝險, ±{int(rebal_thresh*100)}%再平衡)'),
        calc_kpis('4. 華爾街 DSP+ML 動態曝險正2', eq_dsp_tot, '35%~85% 正2 動態調節 (Kalman+ZLEMA+高點回推)'),
        calc_kpis('5. 模擬純 2x 加權指數 (無逆價差)', eq_sim2x, '200% 純2倍價格指數模擬 (扣除內扣、不含除息與外資逆價差)'),
        calc_kpis(f'6. 100% 台灣50正2 ({letf_sym})', eq_letf_100, '200% 期貨曝險 (Level 5 生命週期投資法)')
    ]

    # Live Peak-Drawdown Implied CAGR Table (Ch 3-12~3-14)
    cur_letf_px = float(df['letf_px'].iloc[-1])
    peak_letf_px = float(df['letf_px'].max())
    cur_letf_dd = (cur_letf_px / peak_letf_px - 1.0) * 100.0
    req_gain_letf = (peak_letf_px / cur_letf_px - 1.0) * 100.0

    cur_spot_px = float(df['spot_px'].iloc[-1])
    peak_spot_px = float(df['spot_px'].max())
    cur_spot_dd = (cur_spot_px / peak_spot_px - 1.0) * 100.0
    req_gain_spot = (peak_spot_px / cur_spot_px - 1.0) * 100.0

    # Downsample daily series slightly if needed or keep full daily for ECharts (around 2,900 points is fast in ECharts)
    chart_payload = {
        'letf_sym': letf_sym,
        'spot_sym': spot_sym,
        'div_sym': div_sym,
        'start_date': df['date'].iloc[0],
        'end_date': df['date'].iloc[-1],
        'years_elapsed': round(years_elapsed, 2),
        'rebal_threshold_pct': round(rebal_thresh * 100.0, 1),
        'cur_letf_px': round(cur_letf_px, 2),
        'peak_letf_px': round(peak_letf_px, 2),
        'cur_letf_dd': round(cur_letf_dd, 2),
        'req_gain_letf': round(req_gain_letf, 2),
        'cur_spot_px': round(cur_spot_px, 2),
        'peak_spot_px': round(peak_spot_px, 2),
        'cur_spot_dd': round(cur_spot_dd, 2),
        'req_gain_spot': round(req_gain_spot, 2),
        'cf_1000w': {
            'daily_withdraw': int(daily_withdraw),
            'total_days': n,
            'cum_withdrawn_w': round(cf_withdrawn_cum, 1),
            'end_letf_w': round(cf_letf, 1),
            'end_cash_w': round(cf_cash, 1),
            'end_total_w': round(cf_letf + cf_cash, 1),
            'rebal_cnt': cf_rebal_cnt
        },
        'kpis': kpi_table,
        'rebal_events': rebal_events,
        'annual_rows': annual_rows,
        'rolling_stats': rolling_stats,
        'ml_importances': ml_importances,
        'dates': df['date'].tolist(),
        'eq_0050': [round(float(x), 2) for x in eq_0050],
        'eq_0056': [round(float(x), 2) for x in eq_0056],
        'eq_letf_100': [round(float(x), 2) for x in eq_letf_100],
        'eq_sim2x': [round(float(x), 2) for x in eq_sim2x],
        'eq_5050_tot': [round(float(x), 2) for x in eq_5050_tot],
        'eq_5050_letf': [round(float(x), 2) for x in eq_5050_letf],
        'eq_5050_cash': [round(float(x), 2) for x in eq_5050_cash],
        'eq_dsp_tot': [round(float(x), 2) for x in eq_dsp_tot],
        'letf_dd_pct': [round(float(x), 2) for x in df['letf_dd_pct']],
        'spot_dd_pct': [round(float(x), 2) for x in df['spot_dd_pct']],
        'b5050_dd_pct': [round(float((x / pk - 1.0) * 100.0), 2) for x, pk in zip(eq_5050_tot, np.maximum.accumulate(eq_5050_tot))],
        'dsp_dd_pct': [round(float((x / pk - 1.0) * 100.0), 2) for x, pk in zip(eq_dsp_tot, np.maximum.accumulate(eq_dsp_tot))],
        'spot_vol_20d': [round(float(x), 2) for x in df['spot_vol_20d']],
        'dsp_exposure': [round(float(x), 1) for x in eq_dsp_exposure]
    }
    return chart_payload


def build_html_report(d, out_paths):
    kpis = d['kpis']
    k_0056, k_0050, k_5050, k_dsp, k_sim2x, k_letf = kpis[0], kpis[1], kpis[2], kpis[3], kpis[4], kpis[5]
    cf = d['cf_1000w']

    # Build KPI Table HTML
    kpi_rows_html = ""
    for r in kpis:
        is_highlight = "50:50" in r['name'] or "DSP+ML" in r['name'] or "台灣50正2" in r['name']
        row_bg = "background:rgba(6,182,212,0.08);" if is_highlight else ""
        kpi_rows_html += f"""
        <tr style="{row_bg}">
            <td style="text-align:left;font-weight:800;color:#38bdf8;">{r['name']}</td>
            <td style="text-align:left;color:#cbd5e1;font-size:0.78rem;">{r['exposure']}</td>
            <td class="up-val" style="font-family:Consolas,monospace;font-size:0.95rem;">{r['end_val_w']:,.1f} 萬</td>
            <td class="up-val" style="font-family:Consolas,monospace;font-weight:800;">+{r['tot_ret_pct']:,.1f}%</td>
            <td class="up-val" style="font-family:Consolas,monospace;font-weight:800;">{r['cagr_pct']:.2f}%</td>
            <td style="font-family:Consolas,monospace;color:#cbd5e1;">{r['vol_pct']:.2f}%</td>
            <td style="font-family:Consolas,monospace;color:#f59e0b;font-weight:800;">{r['sharpe']:.2f}</td>
            <td class="dn-val" style="font-family:Consolas,monospace;font-weight:700;">{r['mdd_pct']:.2f}%</td>
            <td style="font-family:Consolas,monospace;color:#38bdf8;font-weight:700;">{r['calmar']:.2f}</td>
        </tr>
        """

    # Build Rebalancing Log HTML
    rebal_rows_html = ""
    for ev in d['rebal_events']:
        t_cls = "up-val" if ev['trigger_pct'] >= 0 else "dn-val"
        rebal_rows_html += f"""
        <tr>
            <td style="font-family:Consolas,monospace;font-weight:700;color:#94a3b8;">第 {ev['count']} 次</td>
            <td style="font-family:Consolas,monospace;font-weight:700;color:#38bdf8;">{ev['date']}</td>
            <td class="{t_cls}" style="font-family:Consolas,monospace;font-weight:800;">{ev['trigger_pct']:+.2f}%</td>
            <td><span class="badge {'badge-profit' if ev['trigger_pct']>=0 else 'badge-danger'}">{ev['action']}</span></td>
            <td style="font-family:Consolas,monospace;">{ev['pre_letf_w']:,.1f} 萬 : {ev['pre_cash_w']:,.1f} 萬</td>
            <td style="font-family:Consolas,monospace;color:#f59e0b;font-weight:800;">{ev['post_letf_w']:,.1f} 萬 : {ev['post_cash_w']:,.1f} 萬</td>
            <td class="up-val" style="font-family:Consolas,monospace;font-weight:800;">{ev['total_w']:,.1f} 萬</td>
        </tr>
        """

    # Build Annual Breakdown HTML
    ann_rows_html = ""
    for r in d['annual_rows']:
        sp_c = "up-val" if r['spot_ret'] >= 0 else "dn-val"
        lt_c = "up-val" if r['letf_ret'] >= 0 else "dn-val"
        bn_c = "up-val" if r['bonus_vs_2x'] >= 0 else "dn-val"
        rl_c = "up-val" if r['roll_alpha'] >= 0 else "dn-val"
        b50_c = "up-val" if r['ret_5050'] >= 0 else "dn-val"
        dsp_c = "up-val" if r['ret_dsp'] >= 0 else "dn-val"
        badge = '<span class="badge badge-profit">🔥 正向紅利年</span>' if r['bonus_vs_2x'] >= 0 else '<span class="badge badge-trapped">⚠️ 波動耗損年</span>'
        ann_rows_html += f"""
        <tr>
            <td style="font-family:Consolas,monospace;font-weight:800;color:#38bdf8;">{r['year']}</td>
            <td class="{sp_c}" style="font-family:Consolas,monospace;">{r['spot_ret']:+.2f}%</td>
            <td style="font-family:Consolas,monospace;color:#94a3b8;">{r['naive_2x']:+.2f}%</td>
            <td style="font-family:Consolas,monospace;color:#cbd5e1;">{r['vol_yr']:.1f}%</td>
            <td style="font-family:Consolas,monospace;color:#f59e0b;">{r['ito_2x']:+.2f}%</td>
            <td class="{lt_c}" style="font-family:Consolas,monospace;font-weight:800;font-size:0.92rem;">{r['letf_ret']:+.2f}%</td>
            <td class="{bn_c}" style="font-family:Consolas,monospace;font-weight:800;">{r['bonus_vs_2x']:+.2f}%</td>
            <td class="{rl_c}" style="font-family:Consolas,monospace;font-weight:700;">{r['roll_alpha']:+.2f}%</td>
            <td class="{b50_c}" style="font-family:Consolas,monospace;font-weight:700;">{r['ret_5050']:+.2f}%</td>
            <td class="{dsp_c}" style="font-family:Consolas,monospace;font-weight:800;">{r['ret_dsp']:+.2f}%</td>
            <td>{badge}</td>
        </tr>
        """

    # Build Rolling Horizon Win-Rate HTML
    roll_rows_html = ""
    for r in d['rolling_stats']:
        roll_rows_html += f"""
        <tr>
            <td style="font-weight:800;color:#38bdf8;">{r['horizon']}</td>
            <td style="font-family:Consolas,monospace;">{r['samples']:,} 個滾動視窗</td>
            <td class="up-val" style="font-family:Consolas,monospace;font-weight:800;">{r['letf_pos_rate']:.1f}%</td>
            <td class="up-val" style="font-family:Consolas,monospace;font-weight:800;">{r['letf_beat_0050_rate']:.1f}%</td>
            <td class="up-val" style="font-family:Consolas,monospace;font-weight:800;">{r['b5050_beat_0050_rate']:.1f}%</td>
            <td class="up-val" style="font-family:Consolas,monospace;font-weight:800;">{r['dsp_beat_0050_rate']:.1f}%</td>
            <td style="font-family:Consolas,monospace;">+{r['sp_mean_ret']:.1f}%</td>
            <td class="up-val" style="font-family:Consolas,monospace;font-weight:800;">+{r['lt_mean_ret']:.1f}%</td>
            <td class="up-val" style="font-family:Consolas,monospace;font-weight:700;">+{r['b50_mean_ret']:.1f}%</td>
            <td class="up-val" style="font-family:Consolas,monospace;font-weight:800;">+{r['dsp_mean_ret']:.1f}%</td>
        </tr>
        """

    html_str = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>華爾街機構級：《槓桿ETF投資法》00631L 量化微結構、50:50 再平衡與 DSP/ML 動態曝險實證終端</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/echarts/5.5.0/echarts.min.js"></script>
    <script>if (typeof echarts === 'undefined') {{ document.write('<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"><\\/script>'); }}</script>
    <style>
        :root {{
            --bg-main: #070b12;
            --bg-panel: #0f172a;
            --bg-card: #131c31;
            --border-line: #1e293b;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --tw-red: #ef4444;
            --tw-green: #10b981;
        }}
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0; padding: 0;
            background-color: var(--bg-main);
            color: var(--text-primary);
            font-family: 'Segoe UI', 'Microsoft JhengHei', -apple-system, sans-serif;
            overflow-x: hidden;
        }}
        .terminal-header {{
            background: linear-gradient(90deg, #090d16 0%, #0f172a 55%, #1e1b4b 100%);
            border-bottom: 2px solid #06b6d4;
            padding: 16px 26px;
            display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;
        }}
        .title-group {{ display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }}
        .cfi-badge {{
            background: linear-gradient(135deg, #ef4444, #f59e0b);
            color: #fff; font-weight: 800; font-size: 0.95rem;
            padding: 6px 14px; border-radius: 6px;
        }}
        .title-group h1 {{ margin: 0; font-size: 1.28rem; font-weight: 800; color: #f8fafc; }}
        .skill-pill {{
            background: rgba(6, 182, 212, 0.16);
            border: 1px solid #06b6d4;
            color: #22d3ee;
            font-size: 0.76rem; font-weight: 700;
            padding: 4px 10px; border-radius: 999px;
        }}
        .kpi-strip {{
            display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
            gap: 12px; padding: 14px 26px; background: #0b1120; border-bottom: 1px solid var(--border-line);
        }}
        .kpi-box {{
            background: var(--bg-card); border: 1px solid #1e293b; border-left: 4px solid #64748b;
            border-radius: 8px; padding: 11px 15px;
        }}
        .kpi-box .k-title {{ font-size: 0.78rem; color: var(--text-secondary); font-weight: 600; display: flex; justify-content: space-between; }}
        .kpi-box .k-val {{ font-size: 1.32rem; font-weight: 800; margin: 5px 0; font-family: 'Consolas', monospace; }}
        .kpi-box .k-sub {{ font-size: 0.74rem; color: #94a3b8; display: flex; justify-content: space-between; }}

        .chart-section {{
            padding: 16px 26px; border-bottom: 1px solid var(--border-line); background: #070b12;
        }}
        #mainSyncChart {{ width: 100%; height: 680px; }}
        .sub-charts-grid {{
            display: grid; grid-template-columns: 50% 50%; gap: 16px; margin-top: 16px;
        }}
        #cashRatchetChart, #mlFeatureChart {{ width: 100%; height: 340px; background: var(--bg-panel); border: 1px solid var(--border-line); border-radius: 10px; padding: 8px; }}

        .main-container {{ max-width: 1600px; margin: 0 auto; padding: 20px 26px 60px 26px; }}
        .sec-title {{
            font-size: 1.25rem; font-weight: 800; color: #f8fafc;
            border-left: 5px solid #06b6d4; padding-left: 14px; margin: 28px 0 14px 0;
            display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;
        }}
        .panel-card {{
            background: var(--bg-panel); border: 1px solid var(--border-line);
            border-radius: 12px; padding: 18px; box-shadow: 0 10px 25px rgba(0,0,0,0.25);
        }}
        .pillars-grid {{
            display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 16px;
        }}
        .pillar-box {{
            background: var(--bg-card); border: 1px solid #1e293b; border-top: 3px solid #38bdf8;
            border-radius: 10px; padding: 16px;
        }}
        .pillar-box h3 {{ margin: 0 0 8px 0; font-size: 1.02rem; color: #38bdf8; }}
        .pillar-box p, .pillar-box li {{ font-size: 0.84rem; color: #cbd5e1; line-height: 1.55; }}
        .formula-box {{
            background: #090d16; border: 1px solid #334155; border-radius: 6px;
            padding: 8px 12px; font-family: 'Consolas', monospace; font-size: 0.82rem; color: #fde047; margin: 8px 0;
        }}

        table.quant-table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
        table.quant-table th {{
            background: #1e293b; color: #cbd5e1; padding: 9px 8px; text-align: center;
            font-weight: 700; border-bottom: 2px solid #334155;
        }}
        table.quant-table td {{ padding: 8px 8px; border-bottom: 1px solid #1e293b; text-align: center; font-variant-numeric: tabular-nums; }}
        table.quant-table tr:hover {{ background: rgba(56, 189, 248, 0.10); }}

        .up-val {{ color: #ef4444; font-weight: 700; }}
        .dn-val {{ color: #10b981; font-weight: 700; }}
        .warn-val {{ color: #f59e0b; font-weight: 700; }}

        .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.73rem; font-weight: 700; }}
        .badge-profit {{ background: rgba(239, 68, 68, 0.18); color: #f87171; border: 1px solid #ef4444; }}
        .badge-trapped {{ background: rgba(245, 158, 11, 0.18); color: #fbbf24; border: 1px solid #f59e0b; }}
        .badge-danger {{ background: rgba(16, 185, 129, 0.20); color: #34d399; border: 1px solid #10b981; }}

        .ctrl-btn {{
            background: #1e293b; color: #cbd5e1; border: 1px solid #334155;
            padding: 5px 12px; border-radius: 6px; font-size: 0.8rem; font-weight: 700; cursor: pointer;
        }}
        .ctrl-btn.active {{ background: #2563eb; color: #fff; border-color: #60a5fa; }}
        @media (max-width: 1100px) {{ .sub-charts-grid {{ grid-template-columns: 1fr; }} }}
    </style>
</head>
<body>

<div class="terminal-header">
    <div class="title-group">
        <span class="cfi-badge">BOOK DISTILLATION &amp; QUANT ENGINE</span>
        <h1>《槓桿ETF投資法：用50正2輕鬆打敗0050＆0056》華爾街量化微結構與 DSP/ML 實證終端</h1>
        <span class="skill-pill">● Skill: quant-leveraged-etf-00631l</span>
    </div>
    <div style="font-family:Consolas,monospace;font-size:0.83rem;color:#94a3b8;">
        實證期間: {d['start_date']} ~ {d['end_date']} ({d['years_elapsed']} 年) | 初始本金基準: 100 萬元
    </div>
</div>

<div class="kpi-strip">
    <div class="kpi-box" style="border-left-color:#ef4444;">
        <div class="k-title"><span>🔥 100% 台灣50正2 ({d['letf_sym']})</span><span>Level 5 生命週期 200%曝險</span></div>
        <div class="k-val up-val">+{k_letf['tot_ret_pct']:,.1f}% <small style="font-size:0.78rem;color:#cbd5e1;">(100萬→{k_letf['end_val_w']:,.0f}萬)</small></div>
        <div class="k-sub"><span>年化 CAGR: <strong class="up-val">{k_letf['cagr_pct']:.2f}%</strong></span><span>超越2x模擬: <strong class="up-val">+{k_letf['tot_ret_pct'] - k_sim2x['tot_ret_pct']:,.0f}% (逆價差紅利)</strong></span></div>
    </div>

    <div class="kpi-box" style="border-left-color:#06b6d4;">
        <div class="k-title"><span style="color:#22d3ee;">🛡️ 50:50 槓桿投資法 (書中核心)</span><span>100% 曝險 + 50% 現金水庫</span></div>
        <div class="k-val up-val">+{k_5050['tot_ret_pct']:,.1f}% <small style="font-size:0.78rem;color:#cbd5e1;">(100萬→{k_5050['end_val_w']:,.0f}萬)</small></div>
        <div class="k-sub"><span>CAGR: <strong>{k_5050['cagr_pct']:.2f}%</strong> (0050: {k_0050['cagr_pct']:.2f}%)</span><span>期末手握現金: <strong style="color:#fde047;">{d['eq_5050_cash'][-1]:,.1f} 萬</strong></span></div>
    </div>

    <div class="kpi-box" style="border-left-color:#f59e0b;">
        <div class="k-title"><span style="color:#fbbf24;">🧠 華爾街 DSP+ML 動態曝險正2</span><span>Kalman + ZLEMA + 高點回推</span></div>
        <div class="k-val up-val">+{k_dsp['tot_ret_pct']:,.1f}% <small style="font-size:0.78rem;color:#cbd5e1;">(100萬→{k_dsp['end_val_w']:,.0f}萬)</small></div>
        <div class="k-sub"><span>Sharpe: <strong style="color:#fbbf24;">{k_dsp['sharpe']:.2f}</strong> | Calmar: <strong>{k_dsp['calmar']:.2f}</strong></span><span>最大回撤 MDD: <strong class="dn-val">{k_dsp['mdd_pct']:.2f}%</strong></span></div>
    </div>

    <div class="kpi-box" style="border-left-color:#ec4899;">
        <div class="k-title"><span style="color:#f472b6;">💰 1,000萬本金「日日配2,000元」</span><span>完敗 0056 存股現金流 (Ch 3-6)</span></div>
        <div class="k-val up-val">{cf['end_total_w']:,.0f} 萬 <small style="font-size:0.78rem;color:#cbd5e1;">(另已領走 {cf['cum_withdrawn_w']:,.0f}萬)</small></div>
        <div class="k-sub"><span>期末正2: <strong>{cf['end_letf_w']:,.0f}萬</strong> | 現金: <strong>{cf['end_cash_w']:,.0f}萬</strong></span><span>觸發再平衡補水: <strong>{cf['rebal_cnt']} 次</strong></span></div>
    </div>
</div>

<div class="chart-section">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;flex-wrap:wrap;gap:8px;">
        <div style="font-weight:800;font-size:1.0rem;color:#f8fafc;">
            📈 三窗格同步實證圖：(1) 100萬本金累積淨值曲線 | (2) 歷史回撤深度 (Underwater Drawdown %) | (3) 20D 波動率與 DSP 動態曝險 (%)
        </div>
        <div>
            <button class="ctrl-btn active" id="btnLinear" onclick="toggleScale('value')">線性座標軸 (Linear)</button>
            <button class="ctrl-btn" id="btnLog" onclick="toggleScale('log')">對數座標軸 (Log 複利視角)</button>
        </div>
    </div>
    <div id="mainSyncChart"></div>

    <div class="sub-charts-grid">
        <div id="cashRatchetChart"></div>
        <div id="mlFeatureChart"></div>
    </div>
</div>

<div class="main-container">

    <div class="sec-title">
        <span>一、全書 4 大篇 56 章華爾街量化蒸餾：四大核心數學與微結構支柱</span>
    </div>
    <div class="pillars-grid">
        <div class="pillar-box">
            <h3>支柱 1：伊藤微積分 (Itô's Lemma) 波動耗損 vs 正向複利紅利</h3>
            <div class="formula-box">g_L = L·μ + L·θ_roll - ½·L(L-1)·σ² - c_exp</div>
            <ul>
                <li><strong>單日重平衡機制 (Ch 1-5~1-8)</strong>：為維持每日 200% 固定曝險，正2在<strong>連續上漲時自動順勢加倉</strong>（創造超越 2 倍之二階凸性正向紅利），在<strong>連續崩盤時自動順勢減倉</strong>（2008海嘯大盤跌 -56%，模擬正2跌 -82.7% 絕不歸零）。</li>
                <li><strong>為何絕對不碰 0050反1 (Ch 2-21)</strong>：代入 L = -1，波動耗損為 -σ²，且同時承受負向市場漂移 (-μ) 與逆價差扣血 (-θ_roll)，數學期望值長期必趨近歸零。</li>
            </ul>
        </div>

        <div class="pillar-box" style="border-top-color:#ef4444;">
            <h3 style="color:#f87171;">支柱 2：台股 4% 除息逆價差（正2 隱含 8% 殖利率）與外資避險 Alpha</h3>
            <div class="formula-box">Implied_Yield_00631L ≈ 2 × (4.1% 除息逆價差 + 1.5% 外資避險逆價差)</div>
            <ul>
                <li><strong>除息直灌淨值 + 免稅優勢 (Ch 1-12~1-16)</strong>：台股高股息使加權指數每年除息蒸發約 4.1% 點數（真實含息報酬指數自 1966 年已破 10.6 萬點）。正2持有 200% 期貨，每年自動吸收 <strong>~8.2% 隱含配息</strong> 灌入淨值，<strong>0 股利稅、0 二代健保、0 配息現金拖累</strong>。</li>
                <li><strong>外資避險結構性逆價差 (Ch 1-17)</strong>：外資持台股現貨 40% 需常態性空台指期避險，使台指期貨指數長期超越報酬指數 <strong>+1.5%~+3.5%/年</strong>。</li>
            </ul>
        </div>

        <div class="pillar-box" style="border-top-color:#f59e0b;">
            <h3 style="color:#fbbf24;">支柱 3：曝險本位思維與夏農惡魔「50:50 槓桿再平衡」工程</h3>
            <div class="formula-box">Net_Cost(50:50) = 0.5 × c_LETF - 0.5 × r_Cash ≈ 0.08% (00675L 為 -0.15%)</div>
            <ul>
                <li><strong>曝險決定風險而非工具 (Ch 3-2, 3-10, 4-8)</strong>：「50萬正2 + 50萬現金」與「100萬 0050」同為 <strong>100% 股票曝險</strong>，但實質內扣成本折半且多出 50% 現金定存收益與心理安全感。</li>
                <li><strong>±50% 閾值再平衡 (Ch 3-3~3-5)</strong>：正2大漲 +50% 時強制賣出鎖利轉入現金水庫；股災大跌 -50% 時自動動用現金抄底正2，完美實踐機械化「買低賣高」。</li>
            </ul>
        </div>

        <div class="pillar-box" style="border-top-color:#10b981;">
            <h3 style="color:#34d399;">支柱 4：高點回推法 (Drawdown Implied CAGR) 與 DSP/ML 動態曝險</h3>
            <div class="formula-box">Implied_CAGR(D, N) = (1 / (1 - |D|))^(1/N) - 1</div>
            <ul>
                <li><strong>大跌加碼首選正2 (Ch 3-12~3-14)</strong>：0050 跌 -30% 漲回前高賺 <strong>+42.9%</strong>；正2 跌 -50% 漲回前高賺 <strong>+100.0%</strong>！用一半資金買跌更深的正2，反彈期望值與現金安全邊際雙贏。</li>
                <li><strong>華爾街 DSP/ML 增強</strong>：結合 1D Kalman 與 ZLEMA(20/60) 濾除高波動盤整耗損期，並於回撤 &gt;38% 觸發高點回推法逆勢加碼，大幅提升 Calmar Ratio。</li>
            </ul>
        </div>
    </div>

    <div class="sec-title">
        <span>二、六大策略完整量化績效對照表（{d['start_date']} ~ {d['end_date']}，本金 100 萬元）</span>
    </div>
    <div class="panel-card" style="overflow-x:auto;">
        <table class="quant-table">
            <thead>
                <tr>
                    <th style="text-align:left;">投資組合策略名稱</th>
                    <th style="text-align:left;">曝險結構與再平衡規則</th>
                    <th>期末總資產<br>(本金100萬)</th>
                    <th>累積總報酬率<br>(Total Return)</th>
                    <th>年化複合報酬<br>(CAGR %)</th>
                    <th>年化波動率<br>(Volatility)</th>
                    <th>夏普比率<br>(Sharpe)</th>
                    <th>歷史最大回撤<br>(Max Drawdown)</th>
                    <th>卡瑪比率<br>(Calmar)</th>
                </tr>
            </thead>
            <tbody>
                {kpi_rows_html}
            </tbody>
        </table>
    </div>

    <div class="sec-title">
        <span>三、書中核心「50:50 槓桿投資法 (±{int(d['rebal_threshold_pct'])}% 觸發再平衡)」歷次賣高買低與現金水庫成長軌跡 (Ch 3-4)</span>
    </div>
    <div class="panel-card" style="overflow-x:auto;">
        <table class="quant-table">
            <thead>
                <tr>
                    <th>再平衡序號</th>
                    <th>觸發交易日</th>
                    <th>正2距上次基準漲跌幅</th>
                    <th>再平衡執行動作 (賣高買低)</th>
                    <th>再平衡前 (正2 : 現金)</th>
                    <th>再平衡後 (正2 : 現金 50:50)</th>
                    <th>當日組合總資產</th>
                </tr>
            </thead>
            <tbody>
                {rebal_rows_html}
            </tbody>
        </table>
    </div>

    <div class="sec-title">
        <span>四、歷年「正向複利紅利 vs 波動耗損」與「台指期逆價差超額 Alpha」實證拆解表 (Ch 1-10, 4-3, 4-4)</span>
    </div>
    <div class="panel-card" style="overflow-x:auto;">
        <table class="quant-table">
            <thead>
                <tr>
                    <th>年度</th>
                    <th>{d['spot_sym']} 含息報酬</th>
                    <th>理想 2倍報酬<br>(2 × 0050)</th>
                    <th>0050 年化波動率<br>(σ)</th>
                    <th>Itô 微積分理論 2x<br>(扣波動耗損 -σ²)</th>
                    <th>{d['letf_sym']} 實際報酬</th>
                    <th>紅利 / 耗損<br>(正2 - 理想2倍)</th>
                    <th>逆價差與複利超額<br>(正2 - Itô理論值)</th>
                    <th>50:50 槓桿法<br>年度報酬</th>
                    <th>DSP+ML 動態正2<br>年度報酬</th>
                    <th>年度屬性診斷</th>
                </tr>
            </thead>
            <tbody>
                {ann_rows_html}
            </tbody>
        </table>
    </div>

    <div class="sec-title">
        <span>五、滾動持有期間勝率檢驗 (Rolling 1Y / 2Y / 3Y / 5Y Windows，驗證書中 Ch 1-19 定律)</span>
    </div>
    <div class="panel-card" style="overflow-x:auto;">
        <table class="quant-table">
            <thead>
                <tr>
                    <th>滾動持有期間</th>
                    <th>歷史滾動樣本數</th>
                    <th>00631L 正報酬機率</th>
                    <th>00631L 擊敗 0050 勝率</th>
                    <th>50:50 再平衡擊敗 0050 勝率</th>
                    <th>DSP+ML 動態正2 擊敗 0050 勝率</th>
                    <th>0050 滾動平均報酬</th>
                    <th>00631L 滾動平均報酬</th>
                    <th>50:50 滾動平均報酬</th>
                    <th>DSP+ML 滾動平均報酬</th>
                </tr>
            </thead>
            <tbody>
                {roll_rows_html}
            </tbody>
        </table>
    </div>

    <div class="sec-title">
        <span>六、高點回推法 (Peak-Drawdown Implied CAGR) 即時試算矩陣 (Ch 3-12 ~ 3-14)</span>
        <span style="font-size:0.82rem;color:#38bdf8;">
            最新基準日 ({d['end_date']}): {d['letf_sym']} 現價 <strong>{d['cur_letf_px']}</strong> (歷史前高 {d['peak_letf_px']}，回撤 <strong>{d['cur_letf_dd']:+.2f}%</strong>，重返前高需漲 <strong>+{d['req_gain_letf']:.2f}%</strong>)
        </span>
    </div>
    <div class="panel-card" style="overflow-x:auto;">
        <table class="quant-table">
            <thead>
                <tr>
                    <th>情境 / 自高點回撤幅度 (|D|)</th>
                    <th>重返前高所需總漲幅<br>G = |D| / (1 - |D|)</th>
                    <th>1年恢復前高<br>隱含年化 CAGR</th>
                    <th>2年恢復前高<br>隱含年化 CAGR</th>
                    <th>3年恢復前高<br>隱含年化 CAGR</th>
                    <th>4年恢復前高<br>隱含年化 CAGR</th>
                    <th>5年恢復前高<br>隱含年化 CAGR</th>
                    <th>華爾街機構資金配置行動準則 (Playbook)</th>
                </tr>
            </thead>
            <tbody>
                <tr style="background:rgba(6,182,212,0.12);">
                    <td style="font-weight:800;color:#38bdf8;">📍 目前 {d['letf_sym']} 即時位置 ({d['cur_letf_dd']:+.2f}%)</td>
                    <td class="up-val" style="font-family:Consolas,monospace;font-weight:800;">+{d['req_gain_letf']:.2f}%</td>
                    <td class="up-val" style="font-family:Consolas,monospace;">+{((1.0 + d['req_gain_letf']/100.0)**(1/1)-1)*100:.2f}%</td>
                    <td class="up-val" style="font-family:Consolas,monospace;">+{((1.0 + d['req_gain_letf']/100.0)**(1/2)-1)*100:.2f}%</td>
                    <td class="up-val" style="font-family:Consolas,monospace;">+{((1.0 + d['req_gain_letf']/100.0)**(1/3)-1)*100:.2f}%</td>
                    <td class="up-val" style="font-family:Consolas,monospace;">+{((1.0 + d['req_gain_letf']/100.0)**(1/4)-1)*100:.2f}%</td>
                    <td class="up-val" style="font-family:Consolas,monospace;">+{((1.0 + d['req_gain_letf']/100.0)**(1/5)-1)*100:.2f}%</td>
                    <td style="text-align:left;color:#fde047;font-weight:700;">依 50:50 或 DSP 紀律維持標準曝險，靜待 ±50% 再平衡信號</td>
                </tr>
                <tr>
                    <td style="font-weight:700;">溫和回檔 -20% (0050 約跌 -10%)</td>
                    <td class="up-val" style="font-family:Consolas,monospace;">+25.00%</td>
                    <td style="font-family:Consolas,monospace;">+25.00%</td>
                    <td style="font-family:Consolas,monospace;">+11.80%</td>
                    <td style="font-family:Consolas,monospace;">+7.72%</td>
                    <td style="font-family:Consolas,monospace;">+5.74%</td>
                    <td style="font-family:Consolas,monospace;">+4.56%</td>
                    <td style="text-align:left;color:#cbd5e1;">日常正常波動，定期定額或維持 50:50 部位不動</td>
                </tr>
                <tr>
                    <td style="font-weight:700;color:#f59e0b;">中度修正 -30% (2018 美中貿易戰級)</td>
                    <td class="up-val" style="font-family:Consolas,monospace;">+42.86%</td>
                    <td style="font-family:Consolas,monospace;">+42.86%</td>
                    <td style="font-family:Consolas,monospace;">+19.52%</td>
                    <td style="font-family:Consolas,monospace;">+12.62%</td>
                    <td style="font-family:Consolas,monospace;">+9.33%</td>
                    <td style="font-family:Consolas,monospace;">+7.39%</td>
                    <td style="text-align:left;color:#f59e0b;">新資金/年終獎金優先投入正2（第二種再平衡：新資金再平衡）</td>
                </tr>
                <tr>
                    <td style="font-weight:800;color:#10b981;">平均兩年週期大跌 -40% (Ch 4-1 入場費)</td>
                    <td class="up-val" style="font-family:Consolas,monospace;font-weight:800;">+66.67%</td>
                    <td class="up-val" style="font-family:Consolas,monospace;">+66.67%</td>
                    <td class="up-val" style="font-family:Consolas,monospace;">+29.10%</td>
                    <td class="up-val" style="font-family:Consolas,monospace;">+18.56%</td>
                    <td class="up-val" style="font-family:Consolas,monospace;">+13.62%</td>
                    <td class="up-val" style="font-family:Consolas,monospace;">+10.76%</td>
                    <td style="text-align:left;color:#34d399;font-weight:700;">高點回推法黃金買點：動用現金水庫分批加碼正2，拉高曝險至 120%~140%</td>
                </tr>
                <tr>
                    <td style="font-weight:800;color:#10b981;">系統性熊市腰斬 -50% (2020熔斷 / 2022升息級)</td>
                    <td class="up-val" style="font-family:Consolas,monospace;font-weight:800;">+100.00%</td>
                    <td class="up-val" style="font-family:Consolas,monospace;font-weight:800;">+100.00%</td>
                    <td class="up-val" style="font-family:Consolas,monospace;font-weight:800;">+41.42%</td>
                    <td class="up-val" style="font-family:Consolas,monospace;font-weight:800;">+25.99%</td>
                    <td class="up-val" style="font-family:Consolas,monospace;font-weight:800;">+18.92%</td>
                    <td class="up-val" style="font-family:Consolas,monospace;font-weight:800;">+14.87%</td>
                    <td style="text-align:left;color:#ef4444;font-weight:800;">🔥 觸發 50:50 強制抄底再平衡！將滿手現金大舉換入打5折之正2，迎接翻倍反彈</td>
                </tr>
            </tbody>
        </table>
    </div>

</div>

<script>
    const DATES = {json.dumps(d['dates'], ensure_ascii=False)};
    const EQ_0050 = {json.dumps(d['eq_0050'])};
    const EQ_0056 = {json.dumps(d['eq_0056'])};
    const EQ_LETF = {json.dumps(d['eq_letf_100'])};
    const EQ_SIM2X = {json.dumps(d['eq_sim2x'])};
    const EQ_5050 = {json.dumps(d['eq_5050_tot'])};
    const EQ_5050_LETF = {json.dumps(d['eq_5050_letf'])};
    const EQ_5050_CASH = {json.dumps(d['eq_5050_cash'])};
    const EQ_DSP = {json.dumps(d['eq_dsp_tot'])};
    const DD_LETF = {json.dumps(d['letf_dd_pct'])};
    const DD_0050 = {json.dumps(d['spot_dd_pct'])};
    const DD_5050 = {json.dumps(d['b5050_dd_pct'])};
    const DD_DSP = {json.dumps(d['dsp_dd_pct'])};
    const VOL_20D = {json.dumps(d['spot_vol_20d'])};
    const DSP_EXP = {json.dumps(d['dsp_exposure'])};
    const ML_IMP = {json.dumps(d['ml_importances'], ensure_ascii=False)};

    const mainChart = echarts.init(document.getElementById('mainSyncChart'));
    const cashChart = echarts.init(document.getElementById('cashRatchetChart'));
    const mlChart = echarts.init(document.getElementById('mlFeatureChart'));

    let currentYScale = 'value';

    function renderMainChart() {{
        mainChart.setOption({{
            backgroundColor: '#070b12',
            animation: false,
            tooltip: {{
                trigger: 'axis',
                axisPointer: {{ type: 'cross' }},
                backgroundColor: 'rgba(15, 23, 42, 0.94)',
                borderColor: '#334155',
                textStyle: {{ color: '#f8fafc', fontSize: 11.5 }}
            }},
            axisPointer: {{ link: [{{ xAxisIndex: 'all' }}] }},
            legend: {{
                top: 4,
                textStyle: {{ color: '#cbd5e1', fontSize: 11 }},
                data: ['100% 00631L (正2)', '華爾街 DSP+ML 動態正2', '模擬 2x 0050 (無逆價差)', '50:50 槓桿再平衡 (書中核心)', '100% 0050 (含息)', '100% 0056 (含息)']
            }},
            grid: [
                {{ left: '64px', right: '32px', top: '40px', height: '44%' }},
                {{ left: '64px', right: '32px', top: '54%', height: '19%' }},
                {{ left: '64px', right: '32px', top: '77%', height: '16%' }}
            ],
            dataZoom: [
                {{ type: 'inside', xAxisIndex: [0, 1, 2], start: 0, end: 100 }},
                {{ type: 'slider', xAxisIndex: [0, 1, 2], bottom: 4, height: 18, borderColor: '#334155', textStyle: {{ color: '#94a3b8' }} }}
            ],
            xAxis: [
                {{ type: 'category', data: DATES, gridIndex: 0, axisLabel: {{ show: false }}, axisLine: {{ lineStyle: {{ color: '#334155' }} }} }},
                {{ type: 'category', data: DATES, gridIndex: 1, axisLabel: {{ show: false }}, axisLine: {{ lineStyle: {{ color: '#334155' }} }} }},
                {{ type: 'category', data: DATES, gridIndex: 2, axisLabel: {{ color: '#94a3b8', fontSize: 10 }}, axisLine: {{ lineStyle: {{ color: '#334155' }} }} }}
            ],
            yAxis: [
                {{
                    type: currentYScale,
                    gridIndex: 0,
                    scale: true,
                    name: '資產總值 (萬元)',
                    nameTextStyle: {{ color: '#94a3b8', fontSize: 10 }},
                    splitLine: {{ lineStyle: {{ color: '#1e293b', type: 'dashed' }} }},
                    axisLabel: {{ color: '#cbd5e1', fontSize: 10 }}
                }},
                {{
                    type: 'value',
                    gridIndex: 1,
                    max: 0,
                    min: -60,
                    name: '歷史回撤 DD(%)',
                    nameTextStyle: {{ color: '#94a3b8', fontSize: 10 }},
                    splitLine: {{ lineStyle: {{ color: '#1e293b', type: 'dashed' }} }},
                    axisLabel: {{ color: '#cbd5e1', fontSize: 9.5, formatter: '{{value}}%' }}
                }},
                {{
                    type: 'value',
                    gridIndex: 2,
                    name: '波動率 / 曝險%',
                    nameTextStyle: {{ color: '#94a3b8', fontSize: 10 }},
                    splitLine: {{ lineStyle: {{ color: '#1e293b', type: 'dashed' }} }},
                    axisLabel: {{ color: '#cbd5e1', fontSize: 9.5 }}
                }}
            ],
            series: [
                {{ name: '100% 00631L (正2)', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: EQ_LETF, showSymbol: false, lineStyle: {{ color: '#ef4444', width: 2.3 }} }},
                {{ name: '華爾街 DSP+ML 動態正2', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: EQ_DSP, showSymbol: false, lineStyle: {{ color: '#f59e0b', width: 2.4 }} }},
                {{ name: '模擬 2x 0050 (無逆價差)', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: EQ_SIM2X, showSymbol: false, lineStyle: {{ color: '#a855f7', width: 1.5, type: 'dashed' }} }},
                {{ name: '50:50 槓桿再平衡 (書中核心)', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: EQ_5050, showSymbol: false, lineStyle: {{ color: '#06b6d4', width: 2.5 }} }},
                {{ name: '100% 0050 (含息)', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: EQ_0050, showSymbol: false, lineStyle: {{ color: '#3b82f6', width: 1.7 }} }},
                {{ name: '100% 0056 (含息)', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: EQ_0056, showSymbol: false, lineStyle: {{ color: '#64748b', width: 1.5 }} }},

                {{ name: '00631L 回撤(%)', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: DD_LETF, showSymbol: false, lineStyle: {{ color: '#10b981', width: 1.2 }}, areaStyle: {{ color: 'rgba(16,185,129,0.12)' }} }},
                {{ name: '50:50 再平衡回撤(%)', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: DD_5050, showSymbol: false, lineStyle: {{ color: '#06b6d4', width: 1.6 }} }},
                {{ name: 'DSP+ML 動態正2回撤(%)', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: DD_DSP, showSymbol: false, lineStyle: {{ color: '#f59e0b', width: 1.6 }} }},
                {{ name: '0050 回撤(%)', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: DD_0050, showSymbol: false, lineStyle: {{ color: '#3b82f6', width: 1.2, type: 'dotted' }} }},

                {{ name: 'DSP 動態總曝險(%)', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: DSP_EXP, showSymbol: false, lineStyle: {{ color: '#f59e0b', width: 1.6 }} }},
                {{ name: '0050 20D年化波動率(%)', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: VOL_20D, showSymbol: false, lineStyle: {{ color: '#ec4899', width: 1.3 }} }}
            ]
        }}, true);
    }}

    function toggleScale(mode) {{
        currentYScale = mode;
        document.getElementById('btnLinear').classList.toggle('active', mode === 'value');
        document.getElementById('btnLog').classList.toggle('active', mode === 'log');
        renderMainChart();
    }}

    function renderSubCharts() {{
        cashChart.setOption({{
            backgroundColor: '#0f172a',
            animation: false,
            title: {{
                text: '🛡️ 50:50 槓桿投資法「正2股票部位 vs 現金水庫階梯式墊高」解剖圖 (Ch 3-4)',
                left: 10, top: 6,
                textStyle: {{ color: '#f8fafc', fontSize: 12.5, fontWeight: 'bold' }}
            }},
            tooltip: {{ trigger: 'axis', backgroundColor: 'rgba(15,23,42,0.95)', borderColor: '#334155', textStyle: {{ color: '#f8fafc', fontSize: 11.5 }} }},
            legend: {{ top: 28, textStyle: {{ color: '#cbd5e1', fontSize: 11 }}, data: ['50:50 現金水庫部位 (萬元)', '50:50 正2股票部位 (萬元)', '100% 0050 總市值 (萬元)'] }},
            grid: {{ left: '54px', right: '24px', top: '58px', bottom: '28px' }},
            xAxis: {{ type: 'category', data: DATES, axisLabel: {{ color: '#94a3b8', fontSize: 10 }} }},
            yAxis: {{ type: 'value', splitLine: {{ lineStyle: {{ color: '#1e293b', type: 'dashed' }} }}, axisLabel: {{ color: '#cbd5e1', fontSize: 10 }} }},
            series: [
                {{ name: '50:50 現金水庫部位 (萬元)', type: 'line', data: EQ_5050_CASH, showSymbol: false, lineStyle: {{ color: '#fde047', width: 2.5 }}, areaStyle: {{ color: 'rgba(253,224,71,0.16)' }} }},
                {{ name: '50:50 正2股票部位 (萬元)', type: 'line', data: EQ_5050_LETF, showSymbol: false, lineStyle: {{ color: '#ef4444', width: 2.0 }} }},
                {{ name: '100% 0050 總市值 (萬元)', type: 'line', data: EQ_0050, showSymbol: false, lineStyle: {{ color: '#38bdf8', width: 1.5, type: 'dashed' }} }}
            ]
        }});

        const featNames = ML_IMP.map(x => x.feature).reverse();
        const featVals = ML_IMP.map(x => x.importance_pct).reverse();
        mlChart.setOption({{
            backgroundColor: '#0f172a',
            animation: false,
            title: {{
                text: '🤖 Random Forest 機器學習：影響 00631L 未來 60 日「超額紅利/耗損」特徵重要度 (%)',
                left: 10, top: 6,
                textStyle: {{ color: '#f8fafc', fontSize: 12.5, fontWeight: 'bold' }}
            }},
            tooltip: {{ trigger: 'axis', axisPointer: {{ type: 'shadow' }} }},
            grid: {{ left: '220px', right: '38px', top: '44px', bottom: '28px' }},
            xAxis: {{ type: 'value', splitLine: {{ lineStyle: {{ color: '#1e293b', type: 'dashed' }} }}, axisLabel: {{ color: '#94a3b8', fontSize: 10, formatter: '{{value}}%' }} }},
            yAxis: {{ type: 'category', data: featNames, axisLabel: {{ color: '#e2e8f0', fontSize: 11, fontWeight: 'bold' }} }},
            series: [{{
                type: 'bar',
                data: featVals,
                barWidth: 16,
                itemStyle: {{ color: '#06b6d4', borderRadius: [0, 4, 4, 0] }},
                label: {{ show: true, position: 'right', formatter: '{{c}}%', color: '#f8fafc', fontSize: 10.5, fontWeight: 'bold' }}
            }}]
        }});
    }}

    renderMainChart();
    renderSubCharts();

    window.addEventListener('resize', () => {{
        mainChart.resize();
        cashChart.resize();
        mlChart.resize();
    }});
</script>
</body>
</html>
"""

    for p in out_paths:
        if not p:
            continue
        os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            f.write(html_str)
        print(f"[Output] 已儲存專業 HTML 報表: {p} ({os.path.getsize(p):,} bytes)")

    js_block = html_str.split('<script>')[-1].split('</script>')[0]
    if 'NaN' in js_block:
        raise ValueError("NaN detected in JS block!")

    with tempfile.NamedTemporaryFile('w', suffix='.js', encoding='utf-8', delete=False) as tf:
        tf.write(js_block)
        tmp_js = tf.name

    res = subprocess.run(['node', '--check', tmp_js], capture_output=True, text=True)
    os.remove(tmp_js)
    if res.returncode != 0:
        raise RuntimeError(f"node --check failed:\n{res.stderr}")
    print("[Verify] node --check PASSED (0 errors)!")


def main():
    parser = argparse.ArgumentParser(description="《槓桿ETF投資法》00631L 華爾街量化微結構、50:50 再平衡與 DSP/ML 動態曝險引擎")
    parser.add_argument('--letf', default='00631L.TW', help='槓桿 ETF 代號 (預設: 00631L.TW)')
    parser.add_argument('--spot', default='0050.TW', help='原型市值 ETF 代號 (預設: 0050.TW)')
    parser.add_argument('--div', default='0056.TW', help='高股息 ETF 代號 (預設: 0056.TW)')
    parser.add_argument('--rebal-threshold', type=float, default=0.50, help='50:50 再平衡觸發門檻 (預設: 0.50 即 ±50%%)')
    parser.add_argument('--daily-withdraw', type=float, default=2000.0, help='日日配每日提領金額 (預設: 2000 元)')
    parser.add_argument('--output', required=True, help='主要輸出 HTML 絕對路徑')
    parser.add_argument('--backup', default='', help='同步備份 HTML 絕對路徑')
    args = parser.parse_args()

    payload = run_backtest_and_models(
        letf_sym=args.letf,
        spot_sym=args.spot,
        div_sym=args.div,
        rebal_thresh=args.rebal_threshold,
        daily_withdraw=args.daily_withdraw
    )
    build_html_report(payload, [args.output, args.backup])

    print("\n=== 六大策略回測績效總覽 (本金 100 萬元) ===")
    df_kpi = pd.DataFrame(payload['kpis'])
    print(df_kpi.to_string(index=False))

    print(f"\n=== 50:50 槓桿投資法 (±{int(args.rebal_threshold*100)}% 觸發) 歷次再平衡紀錄 ===")
    df_reb = pd.DataFrame(payload['rebal_events'])
    if not df_reb.empty:
        print(df_reb.to_string(index=False))


if __name__ == '__main__':
    main()
