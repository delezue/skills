import argparse
import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import urllib.request
import numpy as np
import pandas as pd
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding='utf-8')


def cln(s):
    if not s:
        return 0.0
    s = str(s).replace(',', '').replace('+', '').strip()
    try:
        return float(s)
    except Exception:
        return 0.0


def fetch_goodinfo_margin(stock_id):
    """Scrape Goodinfo ShowMarginChart.asp via Playwright Chrome channel."""
    url = f"https://goodinfo.tw/tw/ShowMarginChart.asp?STOCK_ID={stock_id}&CHT_CAT=DATE"
    print(f"[1/4] 正在透過瀏覽器引擎爬取 Goodinfo: {url} ...")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(
                channel='chrome',
                headless=False,
                args=['--disable-blink-features=AutomationControlled', '--window-position=-2000,-2000']
            )
            page = browser.new_page()
            page.goto(url, wait_until='domcontentloaded', timeout=25000)
            page.wait_for_selector('#tblDetail', timeout=20000)
            page.wait_for_timeout(800)
            title = page.title()
            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, 'html.parser')
        m_name = re.search(rf"{stock_id}\s*([^\s\-]+)", title)
        stock_name = m_name.group(1) if m_name else stock_id

        tbl = soup.find('table', id='tblDetail')
        if not tbl:
            raise RuntimeError("找不到 #tblDetail 表格")

        records = []
        for tr in tbl.find_all('tr'):
            tds = [c.get_text(strip=True) for c in tr.find_all('td')]
            if len(tds) < 20:
                continue
            dt_raw = tds[0]
            if not re.match(r"^'\d{2}/\d{2}/\d{2}$", dt_raw):
                continue
            yy, mm, dd = dt_raw[1:].split('/')
            dt_str = f"20{yy}-{mm}-{dd}"
            records.append({
                'date': dt_str,
                'close': cln(tds[1]),
                'chg': cln(tds[2]),
                'chg_pct': cln(tds[3]),
                'vol_lots': cln(tds[4]),
                'mg_buy': cln(tds[5]),
                'mg_sell': cln(tds[6]),
                'mg_repay': cln(tds[7]),
                'mg_net': cln(tds[8]),
                'mg_bal': cln(tds[9]),
                'mg_use_pct': cln(tds[10]),
                'sh_buy': cln(tds[11]),
                'sh_sell': cln(tds[12]),
                'sh_repay': cln(tds[13]),
                'sh_net': cln(tds[14]),
                'sh_bal': cln(tds[15]),
                'sh_use_pct': cln(tds[16]),
                'offset_lots': cln(tds[17]),
                'margin_daytrade_pct': cln(tds[18]),
                'short_margin_ratio': cln(tds[19]),
                'spot_daytrade_pct': cln(tds[20])
            })

        if len(records) == 0:
            raise RuntimeError("Goodinfo #tblDetail 無有效資料列")

        df = pd.DataFrame(records).sort_values('date').reset_index(drop=True)
        return stock_name, df, "Goodinfo! 台灣股市資訊網 (ShowMarginChart.asp)"
    except Exception as e:
        print(f"[Warn] Goodinfo 直接爬取受阻 ({e})，啟動 FinMind + Yahoo 官方資料備援引擎...")
        return fetch_fallback_margin(stock_id)


def fetch_fallback_margin(stock_id):
    ctx = ssl._create_unverified_context()
    f_url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockMarginPurchaseShortSale&data_id={stock_id}&start_date=2025-10-01"
    req = urllib.request.Request(f_url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
        mg_data = json.loads(r.read().decode('utf-8')).get('data', [])

    df_mg = pd.DataFrame(mg_data)
    # Fetch Yahoo Finance price
    for sfx in [f"{stock_id}.TW", f"{stock_id}.TWO"]:
        y_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sfx}?range=1y&interval=1d"
        try:
            req_y = urllib.request.Request(y_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req_y, context=ctx, timeout=12) as r:
                yd = json.loads(r.read().decode('utf-8'))['chart']['result'][0]
            ts = yd['timestamp']
            q = yd['indicators']['quote'][0]
            df_px = pd.DataFrame({'ts': ts, 'close': q['close'], 'vol': q['volume']})
            df_px['date'] = pd.to_datetime(df_px['ts'], unit='s').dt.tz_localize('UTC').dt.tz_convert('Asia/Taipei').dt.strftime('%Y-%m-%d')
            df_px = df_px.dropna(subset=['close']).drop_duplicates('date', keep='last').sort_values('date')
            break
        except Exception:
            pass

    df = pd.merge(df_mg, df_px[['date', 'close', 'vol']], on='date', how='inner').sort_values('date').reset_index(drop=True)
    df['chg'] = df['close'].diff().fillna(0).round(2)
    df['chg_pct'] = (df['close'].pct_change().fillna(0) * 100).round(2)
    df['vol_lots'] = (df['vol'] / 1000).round(0)
    df['mg_buy'] = df['MarginPurchaseBuy'].astype(float)
    df['mg_sell'] = df['MarginPurchaseSell'].astype(float)
    df['mg_repay'] = df['MarginPurchaseCashRepayment'].astype(float)
    df['mg_bal'] = df['MarginPurchaseTodayBalance'].astype(float)
    df['mg_net'] = df['mg_bal'] - df['MarginPurchaseYesterdayBalance'].astype(float)
    df['sh_bal'] = df['ShortSaleTodayBalance'].astype(float)
    df['sh_net'] = df['sh_bal'] - df['ShortSaleYesterdayBalance'].astype(float)
    return stock_id, df, "TWSE 官方信用交易統計 (FinMind / Yahoo 備援)"


def compute_margin_models(df, ltv=0.60):
    print(f"[2/4] 正在運算四大融資成本線與融資維持率模型 (LTV={ltv*100:.0f}%, 損平維持率={100/ltv:.2f}%)...")
    n = len(df)
    wac_cost = np.zeros(n)
    wac_maint = np.zeros(n)

    init_cost = float(df['close'].iloc[0])
    wac_cost[0] = init_cost
    wac_maint[0] = (init_cost / (ltv * init_cost)) * 100.0

    for i in range(1, n):
        prev_bal = float(df['mg_bal'].iloc[i - 1])
        buy_i = float(df['mg_buy'].iloc[i])
        sell_i = float(df['mg_sell'].iloc[i])
        repay_i = float(df['mg_repay'].iloc[i])
        px_i = float(df['close'].iloc[i])

        out_i = sell_i + repay_i
        rem_old = max(0.0, prev_bal - out_i)
        new_tot = rem_old + buy_i
        c_i = (rem_old * wac_cost[i - 1] + buy_i * px_i) / new_tot if new_tot > 0 else px_i
        wac_cost[i] = c_i
        wac_maint[i] = (px_i / (ltv * c_i)) * 100.0

    df['Cost_WAC'] = np.round(wac_cost, 2)
    df['Maint_WAC'] = np.round(wac_maint, 2)

    # Model B: FIFO Active Cohort
    fifo_cost = np.zeros(n)
    fifo_maint = np.zeros(n)
    for i in range(n):
        target_bal = float(df['mg_bal'].iloc[i])
        acc_lots = 0.0
        acc_val = 0.0
        for j in range(i, -1, -1):
            b_j = float(df['mg_buy'].iloc[j])
            p_j = float(df['close'].iloc[j])
            need = target_bal - acc_lots
            if b_j >= need:
                acc_lots += need
                acc_val += need * p_j
                break
            else:
                acc_lots += b_j
                acc_val += b_j * p_j
        c_fifo = acc_val / acc_lots if acc_lots > 0 else float(df['close'].iloc[i])
        fifo_cost[i] = c_fifo
        fifo_maint[i] = (float(df['close'].iloc[i]) / (ltv * c_fifo)) * 100.0

    df['Cost_FIFO'] = np.round(fifo_cost, 2)
    df['Maint_FIFO'] = np.round(fifo_maint, 2)

    # Model C: 20D Rolling Buy VWAP
    r20_val = (df['mg_buy'] * df['close']).rolling(20, min_periods=1).sum()
    r20_vol = df['mg_buy'].rolling(20, min_periods=1).sum().replace(0, np.nan)
    df['Cost_Roll20'] = (r20_val / r20_vol).fillna(df['close']).round(2)
    df['Maint_Roll20'] = ((df['close'] / (ltv * df['Cost_Roll20'])) * 100.0).round(2)

    # Model D: Full-Period Anchored Buy AVWAP
    c_val = (df['mg_buy'] * df['close']).cumsum()
    c_vol = df['mg_buy'].cumsum().replace(0, np.nan)
    df['Cost_AVWAP'] = (c_val / c_vol).fillna(df['close']).round(2)
    df['Maint_AVWAP'] = ((df['close'] / (ltv * df['Cost_AVWAP'])) * 100.0).round(2)

    # Threshold prices
    df['Warn140_WAC'] = (df['Cost_WAC'] * ltv * 1.40).round(1)
    df['Call130_WAC'] = (df['Cost_WAC'] * ltv * 1.30).round(1)
    df['Warn140_FIFO'] = (df['Cost_FIFO'] * ltv * 1.40).round(1)
    df['Call130_FIFO'] = (df['Cost_FIFO'] * ltv * 1.30).round(1)
    return df.fillna(0)


def build_html_report(stock_id, stock_name, df, src_label, ltv, out_paths):
    print("[3/4] 正在生成深色機構級三窗格互動式 ECharts HTML 報表...")
    breakeven_pct = round(100.0 / ltv, 2)
    last = df.iloc[-1]
    recent_10d_net = float(df['mg_net'].tail(10).sum())

    recent_rows = ""
    for idx in range(len(df) - 1, max(-1, len(df) - 21), -1):
        r = df.iloc[idx]
        chg_cls = "up-val" if r['chg'] >= 0 else "dn-val"
        net_cls = "up-val" if r['mg_net'] >= 0 else "dn-val"
        mw, mf, mr = r['Maint_WAC'], r['Maint_FIFO'], r['Maint_Roll20']
        mw_cls = "up-val" if mw >= breakeven_pct else ("warn-val" if mw >= 140 else "dn-val")
        mf_cls = "up-val" if mf >= breakeven_pct else ("warn-val" if mf >= 140 else "dn-val")
        mr_cls = "up-val" if mr >= breakeven_pct else ("warn-val" if mr >= 140 else "dn-val")
        badge = f'<span class="badge badge-profit">🔥 獲利 (&gt;{breakeven_pct}%)</span>' if mf >= breakeven_pct else f'<span class="badge badge-trapped">⚠️ 破{breakeven_pct}% 套牢</span>'
        recent_rows += f"""
        <tr>
            <td style="font-family:Consolas,monospace;font-weight:700;">{r['date']}</td>
            <td style="font-weight:800;font-family:Consolas,monospace;">{r['close']:,.1f}</td>
            <td class="{chg_cls}">{r['chg']:+.1f} ({r['chg_pct']:+.2f}%)</td>
            <td style="font-family:Consolas,monospace;">{r['vol_lots']:,.0f}</td>
            <td style="font-family:Consolas,monospace;">{r['mg_buy']:,.0f}</td>
            <td style="font-family:Consolas,monospace;">{r['mg_sell']:,.0f}</td>
            <td style="font-family:Consolas,monospace;color:#38bdf8;">{r['mg_repay']:,.0f}</td>
            <td class="{net_cls}" style="font-family:Consolas,monospace;">{r['mg_net']:+,.0f}</td>
            <td style="font-weight:800;font-family:Consolas,monospace;color:#f472b6;">{r['mg_bal']:,.0f}</td>
            <td style="color:#f59e0b;font-family:Consolas,monospace;font-weight:700;">{r['Cost_WAC']:,.1f}</td>
            <td class="{mw_cls}" style="font-family:Consolas,monospace;font-weight:800;">{mw:.2f}%</td>
            <td style="color:#06b6d4;font-family:Consolas,monospace;font-weight:700;">{r['Cost_FIFO']:,.1f}</td>
            <td class="{mf_cls}" style="font-family:Consolas,monospace;font-weight:800;">{mf:.2f}%</td>
            <td class="{mr_cls}" style="font-family:Consolas,monospace;">{mr:.2f}%<br><small style="color:#94a3b8;">(成本:{r['Cost_Roll20']:,.1f})</small></td>
            <td style="font-family:Consolas,monospace;color:#10b981;font-weight:700;">{r['Warn140_FIFO']:,.1f} / {r['Call130_FIFO']:,.1f}</td>
            <td>{badge}</td>
        </tr>
        """

    payload = {
        'dates': df['date'].tolist(),
        'close': df['close'].tolist(),
        'chg': df['chg'].tolist(),
        'mg_buy': df['mg_buy'].tolist(),
        'mg_sell': df['mg_sell'].tolist(),
        'mg_repay': df['mg_repay'].tolist(),
        'mg_net': df['mg_net'].tolist(),
        'mg_bal': df['mg_bal'].tolist(),
        'cost_wac': df['Cost_WAC'].tolist(),
        'maint_wac': df['Maint_WAC'].tolist(),
        'cost_fifo': df['Cost_FIFO'].tolist(),
        'maint_fifo': df['Maint_FIFO'].tolist(),
        'cost_roll20': df['Cost_Roll20'].tolist(),
        'maint_roll20': df['Maint_Roll20'].tolist(),
        'warn140_fifo': df['Warn140_FIFO'].tolist(),
        'call130_fifo': df['Call130_FIFO'].tolist(),
    }

    html_str = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>華爾街機構級：{stock_id} {stock_name} Goodinfo 信用交易爬蟲 × 融資維持率與斷頭追繳精算終端</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/echarts/5.5.0/echarts.min.js"></script>
    <script>if (typeof echarts === 'undefined') {{ document.write('<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"><\\/script>'); }}</script>
    <style>
        :root {{
            --bg-main: #070b12; --bg-panel: #0f172a; --bg-card: #131c31;
            --border-line: #1e293b; --text-primary: #f8fafc; --text-secondary: #94a3b8;
        }}
        * {{ box-sizing: border-box; }}
        body {{ margin: 0; padding: 0; background: var(--bg-main); color: var(--text-primary); font-family: 'Segoe UI', 'Microsoft JhengHei', sans-serif; overflow-x: hidden; }}
        .terminal-header {{ background: linear-gradient(90deg, #090d16 0%, #0f172a 55%, #1e1b4b 100%); border-bottom: 2px solid #ec4899; padding: 16px 26px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }}
        .title-group {{ display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }}
        .stock-badge {{ background: linear-gradient(135deg, #ec4899, #8b5cf6); color: #fff; font-weight: 800; font-size: 1.02rem; padding: 6px 14px; border-radius: 6px; }}
        .title-group h1 {{ margin: 0; font-size: 1.32rem; font-weight: 800; color: #f8fafc; }}
        .kpi-strip {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; padding: 14px 26px; background: #0b1120; border-bottom: 1px solid var(--border-line); }}
        .kpi-box {{ background: var(--bg-card); border: 1px solid #1e293b; border-left: 4px solid #64748b; border-radius: 8px; padding: 11px 15px; }}
        .kpi-box .k-title {{ font-size: 0.78rem; color: var(--text-secondary); font-weight: 600; display: flex; justify-content: space-between; }}
        .kpi-box .k-val {{ font-size: 1.32rem; font-weight: 800; margin: 5px 0; font-family: 'Consolas', monospace; }}
        .kpi-box .k-sub {{ font-size: 0.75rem; color: #94a3b8; display: flex; justify-content: space-between; }}
        .hud-bar {{ background: #090d16; border-bottom: 1px solid #1e293b; padding: 8px 26px; font-family: 'Consolas', 'Microsoft JhengHei', monospace; font-size: 0.83rem; display: flex; flex-wrap: wrap; gap: 16px; align-items: center; }}
        #marginChart {{ width: 100%; height: 800px; background: #070b12; border-bottom: 1px solid var(--border-line); }}
        .main-container {{ max-width: 1540px; margin: 0 auto; padding: 24px 26px 60px 26px; }}
        .sec-title {{ font-size: 1.3rem; font-weight: 800; color: #f8fafc; border-left: 5px solid #ec4899; padding-left: 14px; margin: 28px 0 16px 0; }}
        .panel-card {{ background: var(--bg-panel); border: 1px solid var(--border-line); border-radius: 12px; padding: 20px; box-shadow: 0 10px 25px rgba(0,0,0,0.25); }}
        table.mg-table {{ width: 100%; border-collapse: collapse; font-size: 0.83rem; }}
        table.mg-table th {{ background: #1e293b; color: #cbd5e1; padding: 9px 8px; text-align: center; font-weight: 700; border-bottom: 2px solid #334155; }}
        table.mg-table td {{ padding: 8px 8px; border-bottom: 1px solid #1e293b; text-align: center; font-variant-numeric: tabular-nums; }}
        table.mg-table tr:hover {{ background: rgba(236, 72, 153, 0.08); }}
        .up-val {{ color: #ef4444; font-weight: 700; }}
        .dn-val {{ color: #10b981; font-weight: 700; }}
        .warn-val {{ color: #f59e0b; font-weight: 700; }}
        .badge {{ display: inline-block; padding: 2px 7px; border-radius: 4px; font-size: 0.74rem; font-weight: 700; }}
        .badge-profit {{ background: rgba(239, 68, 68, 0.18); color: #f87171; border: 1px solid #ef4444; }}
        .badge-trapped {{ background: rgba(245, 158, 11, 0.18); color: #fbbf24; border: 1px solid #f59e0b; }}
    </style>
</head>
<body>

<div class="terminal-header">
    <div class="title-group">
        <span class="stock-badge">{stock_id} {stock_name}</span>
        <h1>華爾街機構級：Goodinfo 信用交易爬蟲 × 融資維持率 &amp; 追繳斷頭線精算終端</h1>
    </div>
    <div style="font-family:Consolas,monospace;font-size:0.84rem;color:#94a3b8;">
        資料來源: {src_label} ({df['date'].iloc[0]} ~ {last['date']}, 共 {len(df)} 交易日)
    </div>
</div>

<div class="kpi-strip">
    <div class="kpi-box" style="border-left-color:#ec4899;">
        <div class="k-title"><span>最新收盤 / 融資餘額 ({last['date']})</span><span>單日 {last['mg_net']:+,.0f} 張</span></div>
        <div class="k-val" style="color:#f8fafc;">{last['close']:,.1f} 元 <small style="font-size:0.82rem;color:#f472b6;">({last['mg_bal']:,.0f} 張)</small></div>
        <div class="k-sub"><span>近10日融資增減: <strong>{recent_10d_net:+,.0f} 張</strong></span><span>當日現償: <strong>{last['mg_repay']:,.0f} 張</strong></span></div>
    </div>

    <div class="kpi-box" style="border-left-color:#f59e0b;">
        <div class="k-title"><span style="color:#fbbf24;">📐 模型A: WAC 動態存量池維持率</span><span>損平線 {breakeven_pct}%</span></div>
        <div class="k-val {'up-val' if last['Maint_WAC']>=breakeven_pct else 'warn-val'}">{last['Maint_WAC']:.2f}% <small style="font-size:0.8rem;color:#cbd5e1;">(成本 {last['Cost_WAC']:,.1f})</small></div>
        <div class="k-sub"><span>140%警戒價: <strong>{last['Warn140_WAC']:,.1f} 元</strong></span><span>130%斷頭價: <strong class="dn-val">{last['Call130_WAC']:,.1f} 元</strong></span></div>
    </div>

    <div class="kpi-box" style="border-left-color:#06b6d4;">
        <div class="k-title"><span style="color:#22d3ee;">🔄 模型B: FIFO 先進先出維持率</span><span>場內最新換手籌碼</span></div>
        <div class="k-val {'up-val' if last['Maint_FIFO']>=breakeven_pct else 'warn-val'}">{last['Maint_FIFO']:.2f}% <small style="font-size:0.8rem;color:#cbd5e1;">(成本 {last['Cost_FIFO']:,.1f})</small></div>
        <div class="k-sub"><span>140%警戒價: <strong>{last['Warn140_FIFO']:,.1f} 元</strong></span><span>130%斷頭價: <strong class="dn-val">{last['Call130_FIFO']:,.1f} 元</strong></span></div>
    </div>

    <div class="kpi-box" style="border-left-color:#a855f7;">
        <div class="k-title"><span style="color:#c084fc;">🚨 模型C: 近20日追高融資維持率</span><span>短線浮額健康度</span></div>
        <div class="k-val {'up-val' if last['Maint_Roll20']>=breakeven_pct else 'dn-val'}">{last['Maint_Roll20']:.2f}% <small style="font-size:0.8rem;color:#cbd5e1;">(成本 {last['Cost_Roll20']:,.1f})</small></div>
        <div class="k-sub"><span>20D 140%警戒: <strong>{last['Cost_Roll20']*ltv*1.4:,.1f} 元</strong></span><span>20D 130%斷頭: <strong class="dn-val">{last['Cost_Roll20']*ltv*1.3:,.1f} 元</strong></span></div>
    </div>
</div>

<div class="hud-bar" id="hudBar">
    <span style="color:#f472b6;font-weight:800;">[游標懸浮即時讀值]</span>
    <span>將滑鼠移至下方圖表任一交易日，即可同步檢視當日收盤價、三大融資維持率模型、融資成本線與 130%/140% 斷頭追繳點位...</span>
</div>

<div id="marginChart"></div>

<div class="main-container">
    <div class="sec-title">Goodinfo {stock_id} {stock_name} 近 20 個交易日「融資維持率 × 成本線 × 斷頭價位」逐日精算表</div>
    <div class="panel-card" style="overflow-x:auto;padding:12px;">
        <table class="mg-table">
            <thead>
                <tr>
                    <th>交易日期</th>
                    <th>收盤價</th>
                    <th>漲跌 (%)</th>
                    <th>總成交(張)</th>
                    <th>融資買進</th>
                    <th>融資賣出</th>
                    <th>融資現償</th>
                    <th>融資增減</th>
                    <th style="color:#f472b6;">融資餘額(張)</th>
                    <th style="color:#f59e0b;">WAC存量成本</th>
                    <th style="color:#f59e0b;">WAC維持率(%)</th>
                    <th style="color:#06b6d4;">FIFO周轉成本</th>
                    <th style="color:#06b6d4;">FIFO維持率(%)</th>
                    <th>近20日維持率(成本)</th>
                    <th style="color:#10b981;">140%警戒 / 130%斷頭價</th>
                    <th>散戶部位狀態</th>
                </tr>
            </thead>
            <tbody>
                {recent_rows}
            </tbody>
        </table>
    </div>
</div>

<script>
    const D = {json.dumps(payload, ensure_ascii=False)};
    const myChart = echarts.init(document.getElementById('marginChart'));

    function updateHud(idx) {{
        if (idx < 0 || idx >= D.dates.length) return;
        const dt = D.dates[idx];
        const c = D.close[idx];
        const chg = D.chg[idx];
        const chgCol = chg >= 0 ? '#ef4444' : '#10b981';
        const mf = D.maint_fifo[idx];
        const mfCol = mf >= {breakeven_pct} ? '#ef4444' : '#f59e0b';

        document.getElementById('hudBar').innerHTML = `
            <span style="background:#1e293b;padding:2px 8px;border-radius:4px;font-weight:800;color:#f8fafc;">📅 ${{dt}}</span>
            <span>收盤: <strong style="color:${{chgCol}}">${{c}} 元 (${{chg >= 0 ? '+' : ''}}${{chg}})</strong></span>
            <span style="color:#f472b6;">融資餘額: <strong>${{D.mg_bal[idx].toLocaleString()}} 張</strong> (${{D.mg_net[idx] >= 0 ? '+' : ''}}${{D.mg_net[idx]}} 張 | 現償: ${{D.mg_repay[idx]}} 張)</span>
            <span style="color:#f59e0b;">WAC維持率: <strong>${{D.maint_wac[idx]}}%</strong> (成本 ${{D.cost_wac[idx]}} 元)</span>
            <span style="color:#06b6d4;">FIFO維持率: <strong style="color:${{mfCol}}">${{mf}}%</strong> (成本 ${{D.cost_fifo[idx]}} 元)</span>
            <span style="color:#a855f7;">20D維持率: <strong>${{D.maint_roll20[idx]}}%</strong> (成本 ${{D.cost_roll20[idx]}} 元)</span>
            <span style="color:#10b981;">140%警戒 / 130%斷頭: <strong>${{D.warn140_fifo[idx]}} / ${{D.call130_fifo[idx]}} 元</strong></span>
        `;
    }}

    const option = {{
        backgroundColor: '#070b12',
        animation: false,
        legend: {{
            top: 8,
            textStyle: {{ color: '#cbd5e1', fontSize: 11.5 }},
            data: [
                '收盤價', 'WAC動態存量融資成本線', 'FIFO周轉池融資成本線', '近20日追高融資成本線', '140%融資警戒價位線',
                'WAC動態存量維持率(%)', 'FIFO周轉池維持率(%)', '近20日追高維持率(%)',
                '融資單日增減(張)', '融資總餘額(張)'
            ]
        }},
        tooltip: {{
            trigger: 'axis',
            axisPointer: {{ type: 'cross' }},
            backgroundColor: 'rgba(15, 23, 42, 0.95)',
            borderColor: '#334155',
            textStyle: {{ color: '#f8fafc', fontSize: 12 }},
            formatter: function(params) {{
                if (!params || !params.length) return '';
                const idx = params[0].dataIndex;
                updateHud(idx);
                return `
                    <div style="font-weight:800;border-bottom:1px solid #334155;padding-bottom:4px;margin-bottom:5px;">
                        📅 ${{D.dates[idx]}} | 收盤: ${{D.close[idx]}} 元 (${{D.chg[idx] >= 0 ? '+' : ''}}${{D.chg[idx]}})
                    </div>
                    <div>🟡 WAC 存量維持率: <strong>${{D.maint_wac[idx]}}%</strong> (成本: ${{D.cost_wac[idx]}} 元)</div>
                    <div>🔵 FIFO 周轉維持率: <strong>${{D.maint_fifo[idx]}}%</strong> (成本: ${{D.cost_fifo[idx]}} 元)</div>
                    <div>🟣 近20日維持率: <strong>${{D.maint_roll20[idx]}}%</strong> (成本: ${{D.cost_roll20[idx]}} 元)</div>
                    <div>🚨 140%警戒價 / 130%斷頭價: <strong>${{D.warn140_fifo[idx]}} 元 / ${{D.call130_fifo[idx]}} 元</strong></div>
                    <div style="margin-top:4px;color:#f472b6;">融資餘額: <strong>${{D.mg_bal[idx].toLocaleString()}} 張</strong> (買:${{D.mg_buy[idx]}} / 賣:${{D.mg_sell[idx]}} / 現償:${{D.mg_repay[idx]}})</div>
                `;
            }}
        }},
        axisPointer: {{ link: [{{ xAxisIndex: 'all' }}] }},
        grid: [
            {{ left: '68px', right: '68px', top: '46px', height: '35%' }},
            {{ left: '68px', right: '68px', top: '45%',  height: '24%' }},
            {{ left: '68px', right: '68px', top: '73%',  height: '20%' }}
        ],
        xAxis: [
            {{ type: 'category', data: D.dates, gridIndex: 0, axisLabel: {{ show: false }}, axisLine: {{ lineStyle: {{ color: '#334155' }} }} }},
            {{ type: 'category', data: D.dates, gridIndex: 1, axisLabel: {{ show: false }}, axisLine: {{ lineStyle: {{ color: '#334155' }} }} }},
            {{ type: 'category', data: D.dates, gridIndex: 2, axisLabel: {{ color: '#94a3b8', fontSize: 11 }}, axisLine: {{ lineStyle: {{ color: '#334155' }} }} }}
        ],
        yAxis: [
            {{ scale: true, gridIndex: 0, name: '股價 / 成本線 (元)', nameTextStyle: {{ color: '#cbd5e1', fontSize: 10, padding: [0, 0, 0, 20] }}, splitLine: {{ lineStyle: {{ color: '#1e293b', type: 'dashed' }} }}, axisLabel: {{ color: '#cbd5e1', fontSize: 10 }} }},
            {{ scale: true, gridIndex: 1, name: '融資維持率 (%)', nameTextStyle: {{ color: '#06b6d4', fontSize: 10, padding: [0, 0, 0, 20] }}, splitLine: {{ lineStyle: {{ color: '#1e293b', type: 'dashed' }} }}, axisLabel: {{ color: '#06b6d4', fontSize: 10, formatter: '{{value}}%' }} }},
            {{ scale: true, gridIndex: 2, name: '融資增減(張)', nameTextStyle: {{ color: '#94a3b8', fontSize: 10, padding: [0, 0, 0, 20] }}, splitLine: {{ lineStyle: {{ color: '#1e293b', type: 'dashed' }} }}, axisLabel: {{ color: '#94a3b8', fontSize: 10 }} }},
            {{ scale: true, gridIndex: 2, position: 'right', name: '融資餘額(張)', nameTextStyle: {{ color: '#f472b6', fontSize: 10 }}, splitLine: {{ show: false }}, axisLabel: {{ color: '#f472b6', fontSize: 10 }} }}
        ],
        dataZoom: [
            {{ type: 'inside', xAxisIndex: [0, 1, 2], start: 40, end: 100 }},
            {{ type: 'slider', xAxisIndex: [0, 1, 2], bottom: 6, height: 20, borderColor: '#334155', textStyle: {{ color: '#94a3b8' }} }}
        ],
        series: [
            {{ name: '收盤價', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: D.close, lineStyle: {{ color: '#f8fafc', width: 2.8 }}, itemStyle: {{ color: '#f8fafc' }} }},
            {{ name: 'WAC動態存量融資成本線', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: D.cost_wac, showSymbol: false, lineStyle: {{ color: '#f59e0b', width: 2.2 }} }},
            {{ name: 'FIFO周轉池融資成本線', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: D.cost_fifo, showSymbol: false, lineStyle: {{ color: '#06b6d4', width: 2.4 }} }},
            {{ name: '近20日追高融資成本線', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: D.cost_roll20, showSymbol: false, lineStyle: {{ color: '#a855f7', width: 1.8, type: 'dashed' }} }},
            {{ name: '140%融資警戒價位線', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: D.warn140_fifo, showSymbol: false, lineStyle: {{ color: '#10b981', width: 1.5, type: 'dotted' }} }},
            {{
                name: 'FIFO周轉池維持率(%)', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: D.maint_fifo, showSymbol: false, lineStyle: {{ color: '#06b6d4', width: 2.6 }},
                markLine: {{
                    silent: true, symbol: 'none',
                    data: [
                        {{ yAxis: {breakeven_pct}, lineStyle: {{ color: '#ef4444', width: 1.8, type: 'solid' }}, label: {{ formatter: '{breakeven_pct}% 損益兩平線', color: '#ef4444', fontSize: 10 }} }},
                        {{ yAxis: 140.0, lineStyle: {{ color: '#f59e0b', width: 1.4, type: 'dashed' }}, label: {{ formatter: '140% 追繳警戒線', color: '#f59e0b', fontSize: 10 }} }},
                        {{ yAxis: 130.0, lineStyle: {{ color: '#10b981', width: 1.6, type: 'solid' }}, label: {{ formatter: '130% 斷頭線', color: '#10b981', fontSize: 10 }} }}
                    ]
                }}
            }},
            {{ name: 'WAC動態存量維持率(%)', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: D.maint_wac, showSymbol: false, lineStyle: {{ color: '#f59e0b', width: 2.0 }} }},
            {{ name: '近20日追高維持率(%)', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: D.maint_roll20, showSymbol: false, lineStyle: {{ color: '#a855f7', width: 1.8, type: 'dashed' }} }},
            {{ name: '融資單日增減(張)', type: 'bar', xAxisIndex: 2, yAxisIndex: 2, data: D.mg_net, itemStyle: {{ color: function(p) {{ return p.value >= 0 ? '#ef4444' : '#10b981'; }} }} }},
            {{ name: '融資總餘額(張)', type: 'line', xAxisIndex: 2, yAxisIndex: 3, data: D.mg_bal, showSymbol: false, lineStyle: {{ color: '#f472b6', width: 2.4 }}, areaStyle: {{ color: 'rgba(244, 114, 182, 0.12)' }} }}
        ]
    }};

    myChart.setOption(option);
    updateHud(D.dates.length - 1);
    window.addEventListener('resize', () => myChart.resize());
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
        print(f"  -> 已輸出報表: {p} ({os.path.getsize(p):,} bytes)")

    # Verify JS syntax via node --check
    print("[4/4] 正在執行 node --check 驗證內嵌 JavaScript 語法...")
    js_block = html_str.split('<script>')[-1].split('</script>')[0]
    if 'NaN' in js_block:
        raise ValueError("偵測到非法 NaN 值於 JavaScript 區塊中！")
    with tempfile.NamedTemporaryFile('w', suffix='.js', encoding='utf-8', delete=False) as tf:
        tf.write(js_block)
        tmp_js = tf.name
    try:
        res = subprocess.run(['node', '--check', tmp_js], capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"node --check 失敗:\n{res.stderr}")
        print("  -> node --check 驗證通過 (0 錯誤)！")
    finally:
        if os.path.exists(tmp_js):
            os.remove(tmp_js)


def main():
    parser = argparse.ArgumentParser(description="Goodinfo 個股融資維持率與斷頭點位精算工具")
    parser.add_argument('--stock-id', required=True, help="台股代號，例如 2330, 2317, 2454")
    parser.add_argument('--ltv', type=float, default=0.60, help="法定融資借貸成數，預設 0.60 (60%%)")
    parser.add_argument('--output', required=True, help="主 HTML 輸出路徑")
    parser.add_argument('--backup', default="", help="第二同步輸出路徑 (選填)")
    args = parser.parse_args()

    stock_name, df, src_label = fetch_goodinfo_margin(args.stock_id)
    df = compute_margin_models(df, ltv=args.ltv)
    build_html_report(args.stock_id, stock_name, df, src_label, args.ltv, [args.output, args.backup])

    last = df.iloc[-1]
    print("\n================ 執行摘要 ================")
    print(f"股票: {args.stock_id} {stock_name} | 最新日期: {last['date']} | 收盤價: {last['close']:,.1f} 元")
    print(f"融資餘額: {last['mg_bal']:,.0f} 張 (單日 {last['mg_net']:+,.0f} 張, 現償 {last['mg_repay']:,.0f} 張)")
    print(f"1. WAC 存量池模型 -> 成本: {last['Cost_WAC']:,.2f} 元 | 維持率: {last['Maint_WAC']:.2f}% | 140%警戒: {last['Warn140_WAC']:,.1f} | 130%斷頭: {last['Call130_WAC']:,.1f}")
    print(f"2. FIFO 周轉池模型 -> 成本: {last['Cost_FIFO']:,.2f} 元 | 維持率: {last['Maint_FIFO']:.2f}% | 140%警戒: {last['Warn140_FIFO']:,.1f} | 130%斷頭: {last['Call130_FIFO']:,.1f}")
    print(f"3. 近20日追高批次  -> 成本: {last['Cost_Roll20']:,.2f} 元 | 維持率: {last['Maint_Roll20']:.2f}%")
    print("==========================================")


if __name__ == '__main__':
    main()
