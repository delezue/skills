#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TWSE 全上市股票 (CFICode=ESVUFR) 與 32 大產業別 WAC 融資維持率全景監測引擎
Skill: twse-market-margin-wac
"""

import argparse
import datetime
import json
import os
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
import pandas as pd
from bs4 import BeautifulSoup
from curl_cffi import requests as crequests

sys.stdout.reconfigure(encoding='utf-8')
ctx = ssl._create_unverified_context()


def to_flt(val, default=0.0):
    try:
        return float(str(val).replace(',', '').strip())
    except Exception:
        return default


def scrape_twse_isin(cfi_code='ESVUFR'):
    print(f"[Step 1] 正在爬蟲 https://isin.twse.com.tw/isin/C_public.jsp?strMode=2 (篩選 CFICode = {cfi_code})...")
    isin_url = 'https://isin.twse.com.tw/isin/C_public.jsp?strMode=2'
    req = urllib.request.Request(isin_url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, context=ctx, timeout=25) as r:
        html = r.read().decode('cp950', errors='replace')

    soup = BeautifulSoup(html, 'html.parser')
    esvufr_map = {}
    for tr in soup.find_all('tr'):
        tds = [c.get_text(strip=True) for c in tr.find_all('td')]
        if len(tds) >= 6 and tds[5].strip() == cfi_code:
            parts = tds[0].replace('\u3000', ' ').split(None, 1)
            code = parts[0].strip()
            name = parts[1].strip() if len(parts) > 1 else ''
            ind = tds[4].strip() if tds[4].strip() else '其他業'
            esvufr_map[code] = {
                'code': code,
                'name': name,
                'industry': ind,
                'cfi': tds[5].strip(),
                'list_date': tds[2].strip()
            }
    ind_cnt = len(set(x['industry'] for x in esvufr_map.values()))
    print(f"  -> 共擷取 CFICode={cfi_code} 上市有價證券: {len(esvufr_map)} 檔，涵蓋 {ind_cnt} 個產業別。")
    return esvufr_map


def get_twse_trading_dates(session, target_days=60, cache_dir=None):
    """
    先從 TWSE FMTQIK (每日市場成交資訊) 或快取目錄取得最近 N 個有效交易日 (YYYY-MM-DD)
    """
    found_dates = set()
    if cache_dir and os.path.exists(cache_dir):
        for fname in os.listdir(cache_dir):
            if fname.startswith('day_') and fname.endswith('.json') and len(fname) == 17:
                ymd = fname[4:12]
                dt_iso = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
                found_dates.add(dt_iso)

    today = datetime.date.today()
    for m_offset in range(0, 5):
        dt_Cursor = today - datetime.timedelta(days=28 * m_offset)
        first_day = dt_Cursor.replace(day=1).strftime('%Y%m%d')
        url = f"https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={first_day}&response=json"
        try:
            r = session.get(url, timeout=10)
            d = r.json()
            if d.get('stat') == 'OK' and d.get('data'):
                for row in d['data']:
                    roc_parts = row[0].strip().split('/')
                    if len(roc_parts) == 3:
                        y = int(roc_parts[0]) + 1911
                        dt_iso = f"{y:04d}-{int(roc_parts[1]):02d}-{int(roc_parts[2]):02d}"
                        found_dates.add(dt_iso)
        except Exception:
            pass
        time.sleep(0.1)

    sorted_dates = sorted(list(found_dates))
    if len(sorted_dates) >= target_days:
        return sorted_dates[-target_days:]
    return sorted_dates


def fetch_day_data(session, dt_iso, esvufr_map, cache_dir):
    ymd = dt_iso.replace('-', '')
    cache_file = os.path.join(cache_dir, f"day_{ymd}.json")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cached = json.load(f)
                if cached.get('margin') and cached.get('price'):
                    return dt_iso, cached
        except Exception:
            pass

    mg_url = f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={ymd}&selectType=ALL&response=json"
    px_url = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={ymd}&type=ALLBUT0999&response=json"

    day_res = {'margin': {}, 'price': {}}
    for attempt in range(3):
        try:
            r_mg = session.get(mg_url, timeout=12)
            d_mg = r_mg.json()
            if d_mg.get('stat') == 'OK' and len(d_mg.get('tables', [])) > 1:
                for row in d_mg['tables'][1].get('data', []):
                    c = row[0].strip()
                    if c in esvufr_map:
                        day_res['margin'][c] = [
                            row[2].replace(',', ''),  # buy
                            row[3].replace(',', ''),  # sell
                            row[4].replace(',', ''),  # repay
                            row[5].replace(',', ''),  # prev_bal
                            row[6].replace(',', '')   # curr_bal
                        ]
            time.sleep(0.12)
            r_px = session.get(px_url, timeout=12)
            d_px = r_px.json()
            if d_px.get('stat') == 'OK':
                for tb in d_px.get('tables', []):
                    if len(tb.get('data', [])) > 500:
                        for row in tb['data']:
                            c = row[0].strip()
                            if c in esvufr_map:
                                day_res['price'][c] = row[8].replace(',', '')  # close
                        break
            if day_res['margin'] and day_res['price']:
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(day_res, f)
                return dt_iso, day_res
        except Exception:
            time.sleep(0.5 * (attempt + 1))
    return dt_iso, day_res


def compute_market_and_industry_wac(esvufr_map, target_dates, daily_store, ltv=0.60):
    valid_dates = [d for d in target_dates if daily_store.get(d) and len(daily_store[d]['price']) > 100]
    print(f"[Step 3] 正在精算 {len(esvufr_map)} 檔上市股與各產業別之 WAC 維持率 (有效交易日: {len(valid_dates)} 日, {valid_dates[0]} ~ {valid_dates[-1]})...")

    stock_wac_cost = {}
    stock_prev_px = {}
    stock_history = {c: [] for c in esvufr_map}

    ind_names = sorted(list(set(x['industry'] for x in esvufr_map.values())))
    ind_daily_maint = {ind: [] for ind in ind_names}
    mkt_daily_maint = []

    for d_idx, dt in enumerate(valid_dates):
        mg_dict = daily_store[dt]['margin']
        px_dict = daily_store[dt]['price']

        ind_collateral = {ind: 0.0 for ind in ind_names}
        ind_loan = {ind: 0.0 for ind in ind_names}
        mkt_collateral = 0.0
        mkt_loan = 0.0

        for code, info in esvufr_map.items():
            px_raw = px_dict.get(code, '--')
            prev_valid_px = stock_prev_px.get(code, 0.0)
            px = to_flt(px_raw, prev_valid_px)

            mg_row = mg_dict.get(code)
            if mg_row:
                buy_i = to_flt(mg_row[0])
                sell_i = to_flt(mg_row[1])
                repay_i = to_flt(mg_row[2])
                prev_bal = to_flt(mg_row[3])
                curr_bal = to_flt(mg_row[4])
            else:
                buy_i = sell_i = repay_i = prev_bal = curr_bal = 0.0

            if px <= 0:
                continue

            if code not in stock_wac_cost or stock_wac_cost[code] <= 0:
                stock_wac_cost[code] = px
            else:
                # Corporate action adjustment (stock split / capital reduction > 14.5% single-day jump)
                if prev_valid_px > 0 and abs(px / prev_valid_px - 1.0) > 0.145:
                    stock_wac_cost[code] = stock_wac_cost[code] * (px / prev_valid_px)
                out_i = sell_i + repay_i
                rem_old = max(0.0, prev_bal - out_i)
                new_tot = rem_old + buy_i
                if new_tot > 0:
                    stock_wac_cost[code] = (rem_old * stock_wac_cost[code] + buy_i * px) / new_tot
                else:
                    stock_wac_cost[code] = px

            stock_prev_px[code] = px
            c_wac = stock_wac_cost[code]
            maint_wac = (px / (ltv * c_wac)) * 100.0 if c_wac > 0 else (1.0 / ltv * 100.0)

            if curr_bal > 0:
                col_val = curr_bal * 1000.0 * px
                loan_val = curr_bal * 1000.0 * (ltv * c_wac)
                ind = info['industry']
                ind_collateral[ind] += col_val
                ind_loan[ind] += loan_val
                mkt_collateral += col_val
                mkt_loan += loan_val

            if d_idx >= len(valid_dates) - 10:
                stock_history[code].append({
                    'date': dt,
                    'close': px,
                    'mg_buy': buy_i,
                    'mg_sell': sell_i,
                    'mg_repay': repay_i,
                    'mg_bal': curr_bal,
                    'mg_net': curr_bal - prev_bal,
                    'cost_wac': round(c_wac, 2),
                    'maint_wac': round(maint_wac, 2)
                })

        for ind in ind_names:
            im = round((ind_collateral[ind] / ind_loan[ind]) * 100.0, 2) if ind_loan[ind] > 0 else round(100.0 / ltv, 2)
            ind_daily_maint[ind].append(im)

        mkt_m = round((mkt_collateral / mkt_loan) * 100.0, 2) if mkt_loan > 0 else round(100.0 / ltv, 2)
        mkt_daily_maint.append(mkt_m)

    latest_dt = valid_dates[-1]
    stock_results = []
    for code, info in esvufr_map.items():
        hist = stock_history.get(code, [])
        if not hist:
            stock_results.append({
                'code': code, 'name': info['name'], 'industry': info['industry'],
                'close': 0.0, 'chg_1d_pct': 0.0, 'mg_bal': 0, 'mg_net_1d': 0, 'mg_net_10d': 0,
                'mg_val_m': 0.0, 'loan_val_m': 0.0, 'cost_wac': 0.0, 'maint_wac': 0.0,
                'warn140': 0.0, 'call130': 0.0, 'has_margin': False, 'status': '無融資餘額'
            })
            continue

        last = hist[-1]
        prev = hist[-2] if len(hist) >= 2 else last
        chg_1d_pct = ((last['close'] / prev['close']) - 1.0) * 100.0 if prev['close'] > 0 else 0.0
        mg_net_10d = sum(x['mg_net'] for x in hist)

        px = last['close']
        bal = last['mg_bal']
        cw = last['cost_wac']
        mw = last['maint_wac']
        has_mg = bal > 0

        mg_val_m = (bal * 1000.0 * px) / 1e6 if has_mg else 0.0
        loan_val_m = (bal * 1000.0 * ltv * cw) / 1e6 if has_mg else 0.0

        if not has_mg:
            status = '無融資餘額'
        elif mw < 130.0:
            status = '💀 跌破130%斷頭線'
        elif mw < 140.0:
            status = '🚨 跌破140%警戒線'
        elif mw < 166.67:
            status = '⚠️ 破166.7%套牢區'
        else:
            status = '🔥 高於166.7%獲利區'

        stock_results.append({
            'code': code, 'name': info['name'], 'industry': info['industry'],
            'close': round(px, 2), 'chg_1d_pct': round(chg_1d_pct, 2),
            'mg_bal': int(bal), 'mg_net_1d': int(last['mg_net']), 'mg_net_10d': int(mg_net_10d),
            'mg_val_m': round(mg_val_m, 1), 'loan_val_m': round(loan_val_m, 1),
            'cost_wac': round(cw, 2), 'maint_wac': round(mw, 2) if has_mg else 0.0,
            'warn140': round(cw * ltv * 1.40, 2) if has_mg else 0.0,
            'call130': round(cw * ltv * 1.30, 2) if has_mg else 0.0,
            'has_margin': has_mg, 'status': status
        })

    df_stk = pd.DataFrame(stock_results)

    ind_results = []
    for ind, grp in df_stk.groupby('industry'):
        total_cnt = len(grp)
        mg_grp = grp[grp['has_margin']]
        mg_cnt = len(mg_grp)

        tot_col_m = float(mg_grp['mg_val_m'].sum())
        tot_loan_m = float(mg_grp['loan_val_m'].sum())
        tot_bal = int(mg_grp['mg_bal'].sum())
        net_1d = int(mg_grp['mg_net_1d'].sum())
        net_10d = int(mg_grp['mg_net_10d'].sum())

        weighted_wac_maint = (tot_col_m / tot_loan_m * 100.0) if tot_loan_m > 0 else 166.67
        eq_mean_maint = float(mg_grp['maint_wac'].mean()) if mg_cnt > 0 else 166.67
        eq_med_maint = float(mg_grp['maint_wac'].median()) if mg_cnt > 0 else 166.67

        cnt_profit = int((mg_grp['maint_wac'] >= 166.67).sum())
        cnt_trapped = int(((mg_grp['maint_wac'] >= 140.0) & (mg_grp['maint_wac'] < 166.67)).sum())
        cnt_warn140 = int(((mg_grp['maint_wac'] >= 130.0) & (mg_grp['maint_wac'] < 140.0)).sum())
        cnt_call130 = int((mg_grp['maint_wac'] < 130.0).sum())

        if mg_cnt > 0:
            min_row = mg_grp.sort_values('maint_wac').iloc[0]
            min_stk_str = f"{min_row['code']}{min_row['name']} ({min_row['maint_wac']:.1f}%)"
            top_row = mg_grp.sort_values('mg_val_m', ascending=False).iloc[0]
            top_stk_str = f"{top_row['code']}{top_row['name']} ({top_row['maint_wac']:.1f}%)"
        else:
            min_stk_str = "-"
            top_stk_str = "-"

        ind_results.append({
            'industry': ind,
            'total_stocks': total_cnt,
            'margin_stocks': mg_cnt,
            'tot_bal_lots': tot_bal,
            'net_1d_lots': net_1d,
            'net_10d_lots': net_10d,
            'collateral_yi': round(tot_col_m / 100.0, 2),
            'loan_yi': round(tot_loan_m / 100.0, 2),
            'weighted_maint_wac': round(weighted_wac_maint, 2),
            'equal_mean_maint_wac': round(eq_mean_maint, 2),
            'median_maint_wac': round(eq_med_maint, 2),
            'cnt_profit': cnt_profit,
            'cnt_trapped': cnt_trapped,
            'cnt_warn140': cnt_warn140,
            'cnt_call130': cnt_call130,
            'top_weight_stock': top_stk_str,
            'lowest_maint_stock': min_stk_str
        })

    df_ind = pd.DataFrame(ind_results).sort_values('weighted_maint_wac').reset_index(drop=True)
    return {
        'latest_date': latest_dt,
        'dates': valid_dates,
        'mkt_daily_maint': mkt_daily_maint,
        'ind_daily_maint': ind_daily_maint,
        'industries': df_ind.to_dict(orient='records'),
        'stocks': df_stk.to_dict(orient='records')
    }, df_ind, df_stk


def build_html_report(data, out_paths):
    latest_date = data['latest_date']
    dates = data['dates']
    mkt_daily = data['mkt_daily_maint']
    ind_daily = data['ind_daily_maint']
    industries = data['industries']
    stocks = data['stocks']

    stocks_sorted = sorted(stocks, key=lambda x: (0 if x['has_margin'] else 1, x['maint_wac'] if x['has_margin'] else 9999.0))
    mg_stocks = [s for s in stocks if s['has_margin']]
    tot_col_yi = sum(x['collateral_yi'] for x in industries)
    tot_loan_yi = sum(x['loan_yi'] for x in industries)
    cnt_call130 = sum(1 for s in mg_stocks if s['maint_wac'] < 130.0)
    cnt_warn140 = sum(1 for s in mg_stocks if 130.0 <= s['maint_wac'] < 140.0)
    cnt_trapped = sum(1 for s in mg_stocks if 140.0 <= s['maint_wac'] < 166.67)
    cnt_profit = sum(1 for s in mg_stocks if s['maint_wac'] >= 166.67)

    ind_rows_html = ""
    for idx, r in enumerate(industries, 1):
        ind_name = r['industry']
        wm = r['weighted_maint_wac']
        em = r['equal_mean_maint_wac']
        wm_cls = "up-val" if wm >= 166.67 else ("warn-val" if wm >= 156.0 else "dn-val")
        em_cls = "up-val" if em >= 166.67 else ("warn-val" if em >= 156.0 else "dn-val")
        n10_cls = "up-val" if r['net_10d_lots'] >= 0 else "dn-val"

        if wm >= 166.67:
            ibadge = '<span class="badge badge-profit">🔥 產業融資獲利 (&gt;166.7%)</span>'
        elif wm < 156.5:
            ibadge = '<span class="badge badge-danger">🚨 產業深度套牢 (&lt;156.5%)</span>'
        else:
            ibadge = '<span class="badge badge-trapped">⚠️ 產業融資套牢 (&lt;166.7%)</span>'

        ind_rows_html += f"""
        <tr class="ind-row" onclick="selectIndustry('{ind_name}', true)">
            <td style="font-family:Consolas,monospace;color:#94a3b8;font-weight:700;">#{idx:02d}</td>
            <td style="text-align:left;font-weight:800;color:#38bdf8;">{ind_name}</td>
            <td style="font-family:Consolas,monospace;">{r['margin_stocks']} / {r['total_stocks']}</td>
            <td style="font-family:Consolas,monospace;font-weight:700;color:#f472b6;">{r['collateral_yi']:,.2f} 億</td>
            <td style="font-family:Consolas,monospace;color:#cbd5e1;">{r['loan_yi']:,.2f} 億</td>
            <td style="font-family:Consolas,monospace;">{r['tot_bal_lots']:,}</td>
            <td class="{n10_cls}" style="font-family:Consolas,monospace;">{r['net_10d_lots']:+,}</td>
            <td class="{wm_cls}" style="font-family:Consolas,monospace;font-size:0.95rem;font-weight:800;background:rgba(15,23,42,0.6);">{wm:.2f}%</td>
            <td class="{em_cls}" style="font-family:Consolas,monospace;font-weight:700;">{em:.2f}%</td>
            <td style="font-family:Consolas,monospace;">{r['median_maint_wac']:.2f}%</td>
            <td class="up-val" style="font-family:Consolas,monospace;">{r['cnt_profit']}</td>
            <td class="warn-val" style="font-family:Consolas,monospace;">{r['cnt_trapped']}</td>
            <td class="dn-val" style="font-family:Consolas,monospace;">{r['cnt_warn140']}</td>
            <td style="color:#10b981;font-weight:800;font-family:Consolas,monospace;">{r['cnt_call130']}</td>
            <td style="font-size:0.78rem;text-align:left;">{r['top_weight_stock']}</td>
            <td style="font-size:0.78rem;text-align:left;color:#34d399;">{r['lowest_maint_stock']}</td>
            <td>{ibadge}</td>
        </tr>
        """

    ind_options_html = f'<option value="ALL">全部 {len(industries)} 大產業別 ({len(stocks):,} 檔)</option>\n'
    for r in industries:
        ind_options_html += f'<option value="{r["industry"]}">{r["industry"]} ({r["total_stocks"]}檔 | 加權WAC: {r["weighted_maint_wac"]:.2f}%)</option>\n'

    html_str = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>華爾街機構級：TWSE 上市有價證券 (CFICode=ESVUFR {len(stocks):,}檔) 與 {len(industries)} 大產業別 WAC 融資維持率全景監測終端</title>
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
            background: linear-gradient(135deg, #06b6d4, #3b82f6);
            color: #fff; font-weight: 800; font-size: 1.0rem;
            padding: 6px 14px; border-radius: 6px;
        }}
        .title-group h1 {{ margin: 0; font-size: 1.32rem; font-weight: 800; color: #f8fafc; }}
        .skill-pill {{
            background: rgba(236, 72, 153, 0.16);
            border: 1px solid #ec4899;
            color: #f472b6;
            font-size: 0.76rem; font-weight: 700;
            padding: 4px 10px; border-radius: 999px;
        }}
        .kpi-strip {{
            display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 12px; padding: 14px 26px; background: #0b1120; border-bottom: 1px solid var(--border-line);
        }}
        .kpi-box {{
            background: var(--bg-card); border: 1px solid #1e293b; border-left: 4px solid #64748b;
            border-radius: 8px; padding: 11px 15px;
        }}
        .kpi-box .k-title {{ font-size: 0.78rem; color: var(--text-secondary); font-weight: 600; display: flex; justify-content: space-between; }}
        .kpi-box .k-val {{ font-size: 1.34rem; font-weight: 800; margin: 5px 0; font-family: 'Consolas', monospace; }}
        .kpi-box .k-sub {{ font-size: 0.75rem; color: #94a3b8; display: flex; justify-content: space-between; }}

        .workspace-grid {{
            display: grid; grid-template-columns: 48% 52%;
            border-bottom: 1px solid var(--border-line); background: #070b12;
        }}
        .left-pane {{ border-right: 1px solid var(--border-line); padding: 14px 18px; }}
        .right-pane {{ padding: 14px 18px; }}
        .pane-toolbar {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }}
        .pane-title {{ font-size: 0.96rem; font-weight: 800; color: #f8fafc; }}

        #indBarChart {{ width: 100%; height: 690px; }}
        #indTrendChart {{ width: 100%; height: 340px; }}
        #indScatterChart {{ width: 100%; height: 340px; margin-top: 10px; }}

        .main-container {{ max-width: 1600px; margin: 0 auto; padding: 22px 26px 60px 26px; }}
        .sec-title {{
            font-size: 1.3rem; font-weight: 800; color: #f8fafc;
            border-left: 5px solid #06b6d4; padding-left: 14px; margin: 28px 0 14px 0;
            display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;
        }}
        .panel-card {{
            background: var(--bg-panel); border: 1px solid var(--border-line);
            border-radius: 12px; padding: 18px; box-shadow: 0 10px 25px rgba(0,0,0,0.25);
        }}
        .filter-controls {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
        .ctrl-select, .ctrl-input {{
            background: #1e293b; color: #f8fafc; border: 1px solid #334155;
            padding: 6px 12px; border-radius: 6px; font-size: 0.82rem; font-weight: 600;
        }}
        .flt-btn {{
            background: #1e293b; color: #cbd5e1; border: 1px solid #334155;
            padding: 6px 11px; border-radius: 6px; font-size: 0.8rem; font-weight: 700; cursor: pointer;
        }}
        .flt-btn:hover {{ background: #334155; color: #fff; }}
        .flt-btn.active {{ background: #2563eb; color: #fff; border-color: #60a5fa; }}

        table.quant-table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
        table.quant-table th {{
            background: #1e293b; color: #cbd5e1; padding: 9px 7px; text-align: center;
            font-weight: 700; border-bottom: 2px solid #334155; position: sticky; top: 0; z-index: 5; cursor: pointer;
        }}
        table.quant-table td {{ padding: 7px 7px; border-bottom: 1px solid #1e293b; text-align: center; font-variant-numeric: tabular-nums; }}
        table.quant-table tr.ind-row:hover, table.quant-table tr.stk-row:hover {{ background: rgba(56, 189, 248, 0.12); cursor: pointer; }}

        .up-val {{ color: #ef4444; font-weight: 700; }}
        .dn-val {{ color: #10b981; font-weight: 700; }}
        .warn-val {{ color: #f59e0b; font-weight: 700; }}

        .badge {{ display: inline-block; padding: 2px 7px; border-radius: 4px; font-size: 0.73rem; font-weight: 700; white-space: nowrap; }}
        .badge-profit {{ background: rgba(239, 68, 68, 0.18); color: #f87171; border: 1px solid #ef4444; }}
        .badge-trapped {{ background: rgba(245, 158, 11, 0.18); color: #fbbf24; border: 1px solid #f59e0b; }}
        .badge-danger {{ background: rgba(16, 185, 129, 0.20); color: #34d399; border: 1px solid #10b981; }}
        .badge-none {{ background: rgba(100, 116, 139, 0.2); color: #94a3b8; border: 1px solid #475569; }}

        @media (max-width: 1180px) {{ .workspace-grid {{ grid-template-columns: 1fr; }} }}
    </style>
</head>
<body>

<div class="terminal-header">
    <div class="title-group">
        <span class="cfi-badge">TWSE CFICode = ESVUFR (全 {len(stocks):,} 檔上市普通股)</span>
        <h1>華爾街機構級：上市有價證券 &amp; {len(industries)} 大產業別 WAC 融資維持率全景監測終端</h1>
        <span class="skill-pill">● Skill: twse-market-margin-wac</span>
    </div>
    <div style="font-family:Consolas,monospace;font-size:0.83rem;color:#94a3b8;">
        ISIN 來源: isin.twse.com.tw (strMode=2) | 基準日: {latest_date} ({len(dates)}交易日動態存量池)
    </div>
</div>

<div class="kpi-strip">
    <div class="kpi-box" style="border-left-color:#f59e0b;">
        <div class="k-title"><span>全市場上市股加權 WAC 維持率</span><span>基準線 166.67%</span></div>
        <div class="k-val warn-val">{mkt_daily[-1]:.2f}%</div>
        <div class="k-sub"><span>融資擔保總市值: <strong>{tot_col_yi:,.0f} 億</strong></span><span>總借貸金額: <strong>{tot_loan_yi:,.0f} 億</strong></span></div>
    </div>

    <div class="kpi-box" style="border-left-color:#10b981;">
        <div class="k-title"><span style="color:#34d399;">🚨 破 140% 警戒 &amp; 130% 斷頭個股</span><span>高危斷頭名單</span></div>
        <div class="k-val dn-val">{cnt_call130 + cnt_warn140} 檔 <small style="font-size:0.8rem;color:#cbd5e1;">({cnt_call130}檔破130% / {cnt_warn140}檔破140%)</small></div>
        <div class="k-sub"><span>法定斷頭線: <strong class="dn-val">&lt; 130%</strong></span><span>追繳警戒線: <strong class="warn-val">&lt; 140%</strong></span></div>
    </div>

    <div class="kpi-box" style="border-left-color:#eab308;">
        <div class="k-title"><span style="color:#fde047;">⚠️ 140% ~ 166.7% 融資套牢個股</span><span>套牢結構</span></div>
        <div class="k-val" style="color:#fde047;">{cnt_trapped} / {len(mg_stocks):,} 檔</div>
        <div class="k-sub"><span>獲利區 (&ge;166.7%): <strong class="up-val">{cnt_profit} 檔</strong></span><span>無融資餘額: <strong>{len(stocks) - len(mg_stocks)} 檔</strong></span></div>
    </div>
</div>

<div class="workspace-grid">
    <div class="left-pane">
        <div class="pane-toolbar">
            <div class="pane-title">📊 {len(industries)} 大產業別「加權 WAC 維持率 (%) vs 等權平均維持率 (%)」總排行 (點擊連動右側與表格)</div>
        </div>
        <div id="indBarChart"></div>
    </div>

    <div class="right-pane">
        <div class="pane-toolbar">
            <div class="pane-title" id="rightTrendTitle">📈 產業別 vs 全市場近 {len(dates)} 交易日 WAC 融資維持率動態走勢</div>
            <span style="font-size:0.76rem;color:#94a3b8;">💡 點擊左側產業或下方表格切換產業視角</span>
        </div>
        <div id="indTrendChart"></div>
        <div id="indScatterChart"></div>
    </div>
</div>

<div class="main-container">
    <div class="sec-title">
        <span>一、TWSE {len(industries)} 大產業別 WAC 融資維持率與套牢/追繳分佈彙總表 (點擊任一產業列篩選個股)</span>
    </div>
    <div class="panel-card" style="overflow-x:auto;padding:12px;max-height:540px;overflow-y:auto;">
        <table class="quant-table">
            <thead>
                <tr>
                    <th>排名</th>
                    <th style="text-align:left;">產業別名稱</th>
                    <th>融資家數/<br>總家數</th>
                    <th style="color:#f472b6;">融資擔保市值</th>
                    <th>融資借貸總額</th>
                    <th>融資總餘額<br>(張)</th>
                    <th>近10日融資<br>增減(張)</th>
                    <th style="color:#f59e0b;">產業加權<br>WAC維持率</th>
                    <th style="color:#38bdf8;">產業等權<br>平均維持率</th>
                    <th>產業中位數<br>維持率</th>
                    <th style="color:#ef4444;">獲利家數<br>(&ge;166.7%)</th>
                    <th style="color:#f59e0b;">套牢家數<br>(140~166%)</th>
                    <th style="color:#10b981;">警戒家數<br>(130~140%)</th>
                    <th style="color:#10b981;">斷頭家數<br>(&lt;130%)</th>
                    <th style="text-align:left;">最大融資市值權重股</th>
                    <th style="text-align:left;">該產業最低維持率個股</th>
                    <th>產業融資狀態診斷</th>
                </tr>
            </thead>
            <tbody>
                {ind_rows_html}
            </tbody>
        </table>
    </div>

    <div class="sec-title">
        <span id="stockTableTitle">二、TWSE 上市有價證券 (CFICode = ESVUFR 全 {len(stocks):,} 檔) 個股 WAC 融資維持率完整查詢表</span>
        <div class="filter-controls">
            <select id="indSelect" class="ctrl-select" onchange="applyStockFilters()">
                {ind_options_html}
            </select>
            <input type="text" id="searchInput" class="ctrl-input" placeholder="🔍 輸入代號或股名 (如 2330, 鴻海)..." oninput="applyStockFilters()">
            <button class="flt-btn active" onclick="setStatusFilter('ALL', this)">全部 ({len(stocks):,})</button>
            <button class="flt-btn" onclick="setStatusFilter('CALL130', this)">💀 破130%斷頭 ({cnt_call130})</button>
            <button class="flt-btn" onclick="setStatusFilter('WARN140', this)">🚨 破140%警戒 ({cnt_call130 + cnt_warn140})</button>
            <button class="flt-btn" onclick="setStatusFilter('TRAPPED', this)">⚠️ 套牢區 140~166.7% ({cnt_trapped})</button>
            <button class="flt-btn" onclick="setStatusFilter('PROFIT', this)">🔥 獲利區 &ge;166.7% ({cnt_profit})</button>
            <button class="flt-btn" onclick="sortStocks('maint_asc')">🔼 依維持率低→高</button>
            <button class="flt-btn" onclick="sortStocks('val_desc')">💰 依融資市值大→小</button>
        </div>
    </div>

    <div class="panel-card" style="overflow-x:auto;padding:12px;max-height:760px;overflow-y:auto;">
        <table class="quant-table" id="stockTable">
            <thead>
                <tr>
                    <th>序號</th>
                    <th style="text-align:left;">有價證券代號及名稱</th>
                    <th>產業別</th>
                    <th>最新收盤價</th>
                    <th>單日漲跌(%)</th>
                    <th style="color:#f472b6;">融資餘額(張)</th>
                    <th>單日融資增減</th>
                    <th>近10日融資增減</th>
                    <th>融資擔保市值<br>(百萬元)</th>
                    <th style="color:#f59e0b;">WAC 融資成本</th>
                    <th style="color:#06b6d4;">WAC 融資維持率(%)</th>
                    <th style="color:#f59e0b;">140% 警戒價</th>
                    <th style="color:#10b981;">130% 斷頭價</th>
                    <th>個股融資部位狀態</th>
                </tr>
            </thead>
            <tbody id="stockTbody">
            </tbody>
        </table>
    </div>
</div>

<script>
    const DATES = {json.dumps(dates, ensure_ascii=False)};
    const MKT_DAILY = {json.dumps(mkt_daily, ensure_ascii=False)};
    const IND_DAILY = {json.dumps(ind_daily, ensure_ascii=False)};
    const INDUSTRIES = {json.dumps(industries, ensure_ascii=False)};
    let STOCKS = {json.dumps(stocks_sorted, ensure_ascii=False)};

    let currentStatusFilter = 'ALL';
    let currentSortMode = 'maint_asc';

    const barChart = echarts.init(document.getElementById('indBarChart'));
    const trendChart = echarts.init(document.getElementById('indTrendChart'));
    const scatterChart = echarts.init(document.getElementById('indScatterChart'));

    function renderIndBar() {{
        const sortedInd = [...INDUSTRIES].sort((a, b) => b.weighted_maint_wac - a.weighted_maint_wac);
        const yLabels = sortedInd.map(x => x.industry);
        const wVals = sortedInd.map(x => ({{
            value: x.weighted_maint_wac,
            itemStyle: {{
                color: x.weighted_maint_wac >= 166.67 ? '#ef4444' : (x.weighted_maint_wac < 156.5 ? '#10b981' : '#f59e0b')
            }}
        }}));
        const eVals = sortedInd.map(x => x.equal_mean_maint_wac);

        barChart.setOption({{
            backgroundColor: '#070b12',
            animation: false,
            tooltip: {{
                trigger: 'axis',
                axisPointer: {{ type: 'shadow' }},
                backgroundColor: 'rgba(15, 23, 42, 0.95)',
                borderColor: '#334155',
                textStyle: {{ color: '#f8fafc', fontSize: 12 }}
            }},
            legend: {{
                top: 4,
                textStyle: {{ color: '#cbd5e1', fontSize: 11 }},
                data: ['產業加權 WAC 維持率(%)', '產業等權平均維持率(%)']
            }},
            grid: {{ left: '115px', right: '32px', top: '36px', bottom: '28px' }},
            xAxis: {{
                type: 'value',
                min: 145,
                max: 180,
                splitLine: {{ lineStyle: {{ color: '#1e293b', type: 'dashed' }} }},
                axisLabel: {{ color: '#94a3b8', fontSize: 10, formatter: '{{value}}%' }}
            }},
            yAxis: {{
                type: 'category',
                data: yLabels,
                axisLabel: {{ color: '#e2e8f0', fontSize: 11, fontWeight: 'bold' }},
                axisLine: {{ lineStyle: {{ color: '#334155' }} }}
            }},
            series: [
                {{
                    name: '產業加權 WAC 維持率(%)',
                    type: 'bar',
                    data: wVals,
                    barWidth: 11,
                    label: {{ show: true, position: 'right', formatter: '{{c}}%', color: '#cbd5e1', fontSize: 9.5 }},
                    markLine: {{
                        silent: true,
                        symbol: 'none',
                        data: [
                            {{ xAxis: 166.67, lineStyle: {{ color: '#ef4444', width: 1.8, type: 'solid' }}, label: {{ formatter: '166.7% 損平', color: '#ef4444', fontSize: 10 }} }},
                            {{ xAxis: MKT_DAILY[MKT_DAILY.length - 1], lineStyle: {{ color: '#38bdf8', width: 1.4, type: 'dashed' }}, label: {{ formatter: '全市場 ' + MKT_DAILY[MKT_DAILY.length - 1] + '%', color: '#38bdf8', fontSize: 10 }} }}
                        ]
                    }}
                }},
                {{
                    name: '產業等權平均維持率(%)',
                    type: 'scatter',
                    data: eVals,
                    symbolSize: 8,
                    itemStyle: {{ color: '#38bdf8', borderColor: '#fff', borderWidth: 1 }}
                }}
            ]
        }});

        barChart.on('click', function(params) {{
            if (params && params.name) {{
                selectIndustry(params.name, false);
            }}
        }});
    }}

    function selectIndustry(indName, scrollToTable) {{
        document.getElementById('indSelect').value = indName;
        applyStockFilters();

        const seriesTrend = IND_DAILY[indName] || MKT_DAILY;
        document.getElementById('rightTrendTitle').innerHTML = `📈 <strong>${{indName}}</strong> vs 全市場上市股 近 ${{DATES.length}} 交易日 WAC 維持率走勢`;

        trendChart.setOption({{
            backgroundColor: '#070b12',
            animation: false,
            tooltip: {{
                trigger: 'axis',
                backgroundColor: 'rgba(15, 23, 42, 0.95)',
                borderColor: '#334155',
                textStyle: {{ color: '#f8fafc', fontSize: 12 }}
            }},
            legend: {{
                top: 4,
                textStyle: {{ color: '#cbd5e1', fontSize: 11 }},
                data: [indName + ' 加權WAC維持率(%)', '全市場上市股加權WAC維持率(%)']
            }},
            grid: {{ left: '54px', right: '32px', top: '34px', bottom: '28px' }},
            xAxis: {{
                type: 'category',
                data: DATES,
                axisLabel: {{ color: '#94a3b8', fontSize: 10 }},
                axisLine: {{ lineStyle: {{ color: '#334155' }} }}
            }},
            yAxis: {{
                type: 'value',
                scale: true,
                splitLine: {{ lineStyle: {{ color: '#1e293b', type: 'dashed' }} }},
                axisLabel: {{ color: '#cbd5e1', fontSize: 10, formatter: '{{value}}%' }}
            }},
            series: [
                {{
                    name: indName + ' 加權WAC維持率(%)',
                    type: 'line',
                    data: seriesTrend,
                    showSymbol: false,
                    lineStyle: {{ color: '#06b6d4', width: 2.8 }},
                    areaStyle: {{ color: 'rgba(6, 182, 212, 0.10)' }},
                    markLine: {{
                        silent: true,
                        symbol: 'none',
                        data: [
                            {{ yAxis: 166.67, lineStyle: {{ color: '#ef4444', width: 1.5, type: 'solid' }}, label: {{ formatter: '166.7% 損平', color: '#ef4444', fontSize: 9.5 }} }},
                            {{ yAxis: 140.0, lineStyle: {{ color: '#10b981', width: 1.5, type: 'dashed' }}, label: {{ formatter: '140% 警戒', color: '#10b981', fontSize: 9.5 }} }}
                        ]
                    }}
                }},
                {{
                    name: '全市場上市股加權WAC維持率(%)',
                    type: 'line',
                    data: MKT_DAILY,
                    showSymbol: false,
                    lineStyle: {{ color: '#f59e0b', width: 1.8, type: 'dashed' }}
                }}
            ]
        }}, true);

        const indStocks = STOCKS.filter(s => s.has_margin && (indName === 'ALL' || s.industry === indName));
        const scatData = indStocks.map(s => ({{
            name: s.code + ' ' + s.name,
            value: [Math.max(0.5, s.mg_val_m), s.maint_wac, s.close, s.cost_wac, s.mg_bal],
            symbolSize: Math.max(9, Math.min(28, Math.log10(Math.max(s.mg_val_m, 1)) * 7.5)),
            itemStyle: {{
                color: s.maint_wac >= 166.67 ? '#ef4444' : (s.maint_wac < 140 ? '#10b981' : '#f59e0b')
            }},
            label: {{
                show: indStocks.length <= 45 || s.maint_wac < 140 || s.mg_val_m > 3000,
                formatter: s.name,
                position: 'top',
                color: '#cbd5e1',
                fontSize: 9
            }}
        }}));

        scatterChart.setOption({{
            backgroundColor: '#070b12',
            animation: false,
            title: {{
                text: `🎯 ${{indName}} 成分股「融資市值(百萬, 對數軸) × WAC維持率(%)」分佈 (${{indStocks.length}}檔)`,
                left: 12, top: 4,
                textStyle: {{ color: '#e2e8f0', fontSize: 12, fontWeight: 'bold' }}
            }},
            tooltip: {{
                trigger: 'item',
                backgroundColor: 'rgba(15, 23, 42, 0.95)',
                borderColor: '#334155',
                textStyle: {{ color: '#f8fafc', fontSize: 11.5 }},
                formatter: function(p) {{
                    const v = p.data.value;
                    return `
                        <div style="font-weight:800;border-bottom:1px solid #334155;padding-bottom:3px;margin-bottom:4px;">${{p.data.name}}</div>
                        <div>WAC 融資維持率: <strong>${{v[1]}}%</strong></div>
                        <div>收盤價 / WAC成本: <strong>${{v[2]}} 元 / ${{v[3]}} 元</strong></div>
                        <div>融資餘額 / 市值: <strong>${{v[4].toLocaleString()}} 張 (${{v[0].toLocaleString()}} 百萬元)</strong></div>
                    `;
                }}
            }},
            grid: {{ left: '54px', right: '32px', top: '36px', bottom: '36px' }},
            xAxis: {{
                type: 'log',
                name: '融資擔保市值 (百萬元, Log軸)',
                nameLocation: 'middle',
                nameGap: 22,
                nameTextStyle: {{ color: '#94a3b8', fontSize: 10 }},
                splitLine: {{ lineStyle: {{ color: '#1e293b', type: 'dashed' }} }},
                axisLabel: {{ color: '#94a3b8', fontSize: 9.5 }}
            }},
            yAxis: {{
                type: 'value',
                scale: true,
                name: 'WAC維持率(%)',
                nameTextStyle: {{ color: '#94a3b8', fontSize: 10 }},
                splitLine: {{ lineStyle: {{ color: '#1e293b', type: 'dashed' }} }},
                axisLabel: {{ color: '#cbd5e1', fontSize: 10, formatter: '{{value}}%' }}
            }},
            series: [{{
                type: 'scatter',
                data: scatData,
                markLine: {{
                    silent: true,
                    symbol: 'none',
                    data: [
                        {{ yAxis: 166.67, lineStyle: {{ color: '#ef4444', width: 1.4 }} }},
                        {{ yAxis: 140.0, lineStyle: {{ color: '#10b981', width: 1.4, type: 'dashed' }} }}
                    ]
                }}
            }}]
        }}, true);

        if (scrollToTable) {{
            document.getElementById('stockTableTitle').scrollIntoView({{ behavior: 'smooth', block: 'start' }});
        }}
    }}

    function setStatusFilter(mode, btnEl) {{
        currentStatusFilter = mode;
        document.querySelectorAll('.filter-controls .flt-btn').forEach(b => {{
            if (b.textContent.includes('全部') || b.textContent.includes('破') || b.textContent.includes('套牢') || b.textContent.includes('獲利')) {{
                b.classList.remove('active');
            }}
        }});
        if (btnEl) btnEl.classList.add('active');
        applyStockFilters();
    }}

    function sortStocks(mode) {{
        currentSortMode = mode;
        if (mode === 'maint_asc') {{
            STOCKS.sort((a, b) => (a.has_margin === b.has_margin) ? (a.maint_wac - b.maint_wac) : (a.has_margin ? -1 : 1));
        }} else if (mode === 'val_desc') {{
            STOCKS.sort((a, b) => b.mg_val_m - a.mg_val_m);
        }}
        applyStockFilters();
    }}

    function applyStockFilters() {{
        const indVal = document.getElementById('indSelect').value;
        const kw = document.getElementById('searchInput').value.trim().toLowerCase();

        const filtered = STOCKS.filter(s => {{
            if (indVal !== 'ALL' && s.industry !== indVal) return false;
            if (kw && !(s.code.toLowerCase().includes(kw) || s.name.toLowerCase().includes(kw) || s.industry.toLowerCase().includes(kw))) return false;
            if (currentStatusFilter === 'CALL130') return s.has_margin && s.maint_wac < 130.0;
            if (currentStatusFilter === 'WARN140') return s.has_margin && s.maint_wac < 140.0;
            if (currentStatusFilter === 'TRAPPED') return s.has_margin && s.maint_wac >= 140.0 && s.maint_wac < 166.67;
            if (currentStatusFilter === 'PROFIT') return s.has_margin && s.maint_wac >= 166.67;
            return true;
        }});

        document.getElementById('stockTableTitle').textContent = `二、TWSE 上市有價證券 (CFICode = ESVUFR) 個股 WAC 融資維持率查詢表 (符合條件: ${{filtered.length}} 檔)`;

        let html = '';
        for (let i = 0; i < filtered.length; i++) {{
            const s = filtered[i];
            const chgCls = s.chg_1d_pct >= 0 ? 'up-val' : 'dn-val';
            const n1Cls = s.mg_net_1d >= 0 ? 'up-val' : 'dn-val';
            const n10Cls = s.mg_net_10d >= 0 ? 'up-val' : 'dn-val';
            let mwCls = '';
            let badge = '<span class="badge badge-none">無融資餘額</span>';
            if (s.has_margin) {{
                if (s.maint_wac < 130.0) {{
                    mwCls = 'dn-val';
                    badge = '<span class="badge badge-danger">💀 跌破130%斷頭線</span>';
                }} else if (s.maint_wac < 140.0) {{
                    mwCls = 'dn-val';
                    badge = '<span class="badge badge-danger">🚨 跌破140%警戒線</span>';
                }} else if (s.maint_wac < 166.67) {{
                    mwCls = 'warn-val';
                    badge = '<span class="badge badge-trapped">⚠️ 破166.7%套牢區</span>';
                }} else {{
                    mwCls = 'up-val';
                    badge = '<span class="badge badge-profit">🔥 高於166.7%獲利區</span>';
                }}
            }}

            html += `<tr class="stk-row">
                <td style="font-family:Consolas,monospace;color:#94a3b8;">${{i + 1}}</td>
                <td style="text-align:left;font-weight:800;"><span style="color:#38bdf8;font-family:Consolas,monospace;margin-right:6px;">${{s.code}}</span>${{s.name}}</td>
                <td style="color:#cbd5e1;font-size:0.78rem;">${{s.industry}}</td>
                <td style="font-family:Consolas,monospace;font-weight:700;">${{s.close > 0 ? s.close.toFixed(2) : '-'}}</td>
                <td class="${{chgCls}}" style="font-family:Consolas,monospace;">${{s.chg_1d_pct >= 0 ? '+' : ''}}${{s.chg_1d_pct.toFixed(2)}}%</td>
                <td style="font-family:Consolas,monospace;color:#f472b6;font-weight:700;">${{s.mg_bal.toLocaleString()}}</td>
                <td class="${{n1Cls}}" style="font-family:Consolas,monospace;">${{s.mg_net_1d >= 0 ? '+' : ''}}${{s.mg_net_1d.toLocaleString()}}</td>
                <td class="${{n10Cls}}" style="font-family:Consolas,monospace;">${{s.mg_net_10d >= 0 ? '+' : ''}}${{s.mg_net_10d.toLocaleString()}}</td>
                <td style="font-family:Consolas,monospace;">${{s.mg_val_m.toLocaleString()}}</td>
                <td style="font-family:Consolas,monospace;color:#f59e0b;font-weight:700;">${{s.has_margin ? s.cost_wac.toFixed(2) : '-'}}</td>
                <td class="${{mwCls}}" style="font-family:Consolas,monospace;font-size:0.92rem;font-weight:800;">${{s.has_margin ? s.maint_wac.toFixed(2) + '%' : '-'}}</td>
                <td style="font-family:Consolas,monospace;color:#f59e0b;">${{s.has_margin ? s.warn140.toFixed(1) : '-'}}</td>
                <td style="font-family:Consolas,monospace;color:#10b981;font-weight:700;">${{s.has_margin ? s.call130.toFixed(1) : '-'}}</td>
                <td>${{badge}}</td>
            </tr>`;
        }}
        document.getElementById('stockTbody').innerHTML = html;
    }}

    renderIndBar();
    selectIndustry('半導體業', false);
    document.getElementById('indSelect').value = 'ALL';
    applyStockFilters();

    window.addEventListener('resize', () => {{
        barChart.resize();
        trendChart.resize();
        scatterChart.resize();
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
    parser = argparse.ArgumentParser(description="TWSE 全上市股票 (CFICode=ESVUFR) 與 32 大產業別 WAC 融資維持率精算引擎")
    parser.add_argument('--cfi', default='ESVUFR', help='篩選之 CFICode (預設: ESVUFR)')
    parser.add_argument('--days', type=int, default=60, help='滾動計算之交易日數 (預設: 60)')
    parser.add_argument('--ltv', type=float, default=0.60, help='融資借貸成數 (預設: 0.60 即 60%%)')
    parser.add_argument('--output', required=True, help='主要輸出 HTML 絕對路徑')
    parser.add_argument('--backup', default='', help='同步備份 HTML 絕對路徑')
    parser.add_argument('--cache-dir', default='', help='TWSE 日級資料快取目錄')
    args = parser.parse_args()

    skill_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cache_dir = args.cache_dir if args.cache_dir else os.path.join(skill_root, 'cache')
    os.makedirs(cache_dir, exist_ok=True)

    esvufr_map = scrape_twse_isin(args.cfi)
    session = crequests.Session(impersonate="chrome")
    target_dates = get_twse_trading_dates(session, target_days=args.days, cache_dir=cache_dir)
    print(f"[Step 2] 準備載入/抓取 {len(target_dates)} 個交易日 ({target_dates[0]} ~ {target_dates[-1]}) 之 TWSE 全市場信用交易與行情...")

    daily_store = {}
    t_start = time.time()
    for idx, dt_iso in enumerate(target_dates):
        dt_k, data = fetch_day_data(session, dt_iso, esvufr_map, cache_dir)
        daily_store[dt_k] = data
        if (idx + 1) % 15 == 0 or idx == len(target_dates) - 1:
            print(f"  -> 進度 {idx+1}/{len(target_dates)} ({dt_iso}), 耗時 {time.time()-t_start:.1f}s")

    payload, df_ind, df_stk = compute_market_and_industry_wac(esvufr_map, target_dates, daily_store, ltv=args.ltv)
    build_html_report(payload, [args.output, args.backup])

    print(f"\n=== 全市場 (CFICode={args.cfi}) 加權 WAC 融資維持率 ({payload['latest_date']}): {payload['mkt_daily_maint'][-1]:.2f}% ===")
    cols_ind = ['industry', 'total_stocks', 'margin_stocks', 'collateral_yi', 'weighted_maint_wac', 'equal_mean_maint_wac', 'cnt_profit', 'cnt_trapped', 'cnt_warn140', 'cnt_call130', 'lowest_maint_stock']
    print(df_ind[cols_ind].to_string(index=False))


if __name__ == '__main__':
    main()
