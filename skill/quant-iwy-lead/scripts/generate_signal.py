import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

def calc_zlema(series, n):
    lag = int((n - 1) / 2)
    lag_series = series.shift(lag)
    adj_series = series + (series - lag_series)
    return adj_series.ewm(span=n, adjust=False).mean()

def get_zlema_bbi(series, periods=[13, 21, 34, 55]):
    return sum([calc_zlema(series, p) for p in periods]) / len(periods)

def generate_report():
    print("Fetching latest data for IWY and ^TWII...")
    # Fetch 1 year of data to calculate moving averages properly
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365)
    
    df = yf.download(['IWY', '^TWII'], start=start_date.strftime('%Y-%m-%d'), progress=False)
    close_df = df['Close'].dropna()
    
    if close_df.empty:
        print("Failed to fetch data.")
        return
        
    # Calculate IWY ZLEMA BBI
    close_df['IWY_BBI'] = get_zlema_bbi(close_df['IWY'])
    
    # Get last 5 days
    recent = close_df.tail(5).copy()
    recent['IWY_Signal'] = np.where(recent['IWY'] > recent['IWY_BBI'], 1, 0)
    
    latest_date = recent.index[-1].strftime('%Y-%m-%d')
    latest_iwy = recent['IWY'].iloc[-1]
    latest_bbi = recent['IWY_BBI'].iloc[-1]
    latest_twii = recent['^TWII'].iloc[-1]
    dist_pct = (latest_iwy - latest_bbi) / latest_bbi * 100
    
    # Analyze trend and state
    signal_today = recent['IWY_Signal'].iloc[-1]
    signal_yesterday = recent['IWY_Signal'].iloc[-2]
    
    state = ""
    action = ""
    color = ""
    icon = ""
    
    if signal_today == 1 and signal_yesterday == 1:
        if dist_pct > 3:
            state = "多頭強勢 (過熱風險)"
            action = "持有 (Hold) / 停止加倉"
            color = "#10b981"
            icon = "🔥"
        else:
            state = "多頭格局 (穩健)"
            action = "持有 (Hold) / 逢低加倉"
            color = "#22c55e"
            icon = "📈"
    elif signal_today == 1 and signal_yesterday == 0:
        state = "剛轉多頭 (黃金交叉)"
        action = "建倉 (Build Position)"
        color = "#3b82f6"
        icon = "🚀"
    elif signal_today == 0 and signal_yesterday == 1:
        state = "剛轉空頭 (死亡交叉)"
        action = "清倉 / 大幅減碼 (Clear / Reduce)"
        color = "#ef4444"
        icon = "🚨"
    elif signal_today == 0 and signal_yesterday == 0:
        if dist_pct < -3:
            state = "空頭急跌 (超賣)"
            action = "空手觀望 (Wait) / 勿抄底"
            color = "#b91c1c"
            icon = "🥶"
        else:
            state = "空頭弱勢 (盤跌)"
            action = "空手觀望 (Wait) / 持有現金"
            color = "#f97316"
            icon = "📉"

    # Generate historical table
    table_html = ""
    for idx, row in recent.sort_index(ascending=False).iterrows():
        dt = idx.strftime('%Y-%m-%d')
        iwy_price = row['IWY']
        bbi = row['IWY_BBI']
        diff = (iwy_price - bbi) / bbi * 100
        status = "<span style='color: #10b981; font-weight: bold;'>多頭 (站上)</span>" if iwy_price > bbi else "<span style='color: #ef4444; font-weight: bold;'>空頭 (跌破)</span>"
        
        table_html += f"""
        <tr>
            <td>{dt}</td>
            <td>${iwy_price:.2f}</td>
            <td>${bbi:.2f}</td>
            <td>{diff:+.2f}%</td>
            <td>{status}</td>
        </tr>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html lang="zh-TW">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>IWY 領先指標量化訊號中心</title>
        <style>
            :root {{
                --primary: #0f172a;
                --bg: #f8fafc;
            }}
            body {{ font-family: 'Segoe UI', sans-serif; background: var(--bg); color: #334155; padding: 40px; margin: 0; line-height: 1.7; }}
            .container {{ max-width: 900px; margin: auto; background: white; padding: 40px; border-radius: 12px; box-shadow: 0 10px 20px rgba(0,0,0,0.08); border-top: 6px solid {color}; }}
            h1 {{ text-align: center; color: var(--primary); margin-bottom: 5px; }}
            .subtitle {{ text-align: center; color: #64748b; margin-bottom: 30px; font-weight: 500; }}
            
            .dashboard {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 30px; }}
            .panel {{ background: #f1f5f9; padding: 25px; border-radius: 8px; text-align: center; }}
            .panel.main {{ background: {color}15; border: 2px solid {color}; }}
            .panel h3 {{ margin: 0 0 10px 0; color: #64748b; font-size: 1.1em; }}
            .panel .val {{ font-size: 2.2em; font-weight: bold; color: var(--primary); margin: 0; }}
            .panel.main .val {{ color: {color}; }}
            .panel .sub-val {{ font-size: 1em; color: #64748b; margin-top: 5px; }}

            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; margin-bottom: 30px; }}
            th, td {{ padding: 12px; text-align: center; border-bottom: 1px solid #e2e8f0; }}
            th {{ background: #f8fafc; color: #475569; }}
            
            .manual {{ background: #fffbeb; padding: 30px; border-left: 5px solid #eab308; border-radius: 8px; margin-top: 30px; }}
            .manual h3 {{ margin-top: 0; color: #b45309; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🤖 量化訊號：IWY (美股巨頭) 領先指標</h1>
            <div class="subtitle">更新時間：{latest_date} | 演算法：ZLEMA-BBI (13/21/34/55)</div>
            
            <div class="dashboard">
                <div class="panel main">
                    <h3>{icon} 當前盤勢判定</h3>
                    <p class="val">{state}</p>
                    <p class="sub-val" style="font-weight: bold;">操作建議：{action}</p>
                </div>
                <div class="panel">
                    <h3>IWY 乖離距離 (距 BBI 防守線)</h3>
                    <p class="val" style="color: {'#10b981' if dist_pct > 0 else '#ef4444'};">{dist_pct:+.2f}%</p>
                    <p class="sub-val">IWY: ${latest_iwy:.2f} | BBI: ${latest_bbi:.2f}</p>
                </div>
            </div>

            <h3>📅 近五日 IWY 多空防守戰況</h3>
            <table>
                <thead>
                    <tr>
                        <th>日期</th>
                        <th>IWY 收盤價</th>
                        <th>ZLEMA-BBI 陣線</th>
                        <th>乖離率</th>
                        <th>多空狀態</th>
                    </tr>
                </thead>
                <tbody>
                    {table_html}
                </tbody>
            </table>

            <div class="manual">
                <h3>📘 【實戰操作手冊】1800萬資金控管 SOP</h3>
                <p>此系統專為 <strong>大資金操作台股大盤 (如正二 00685L)</strong> 設計，利用美股巨頭 IWY 作為時間上的領先哨兵。</p>
                
                <strong>第一步：每日確認訊號 (台灣時間早上 09:00 開盤前)</strong>
                <ul>
                    <li>看一眼本報告的「操作建議」。由於 IWY 是美股，台灣早上 9 點開盤前，美股已經收盤，訊號已經完全底定 (無未來函數)。</li>
                </ul>

                <strong>第二步：嚴格執行紀律</strong>
                <ul>
                    <li><strong>🚀 建倉 (剛站上 BBI)：</strong> 將您的防禦現金分批打入台股。這是趨勢反轉向上的第一天，不要猶豫。</li>
                    <li><strong>📈 持有 / 加倉：</strong> 只要 IWY 穩穩站在 BBI 之上，台股的震盪都是洗盤，死抱正二不要被洗掉。若乖離拉近 BBI 但未跌破，可逢低加倉。</li>
                    <li><strong>🚨 清倉 (剛跌破 BBI)：</strong> 這是最關鍵的一擊。當 IWY 跌破 BBI 的那一刻，無論台股盤面看起來多強，<strong>請立刻在 09:00 開盤將正二清倉或大幅減碼</strong>。這能幫您閃過 2022 年那種毀滅級股災。</li>
                    <li><strong>📉 空手觀望：</strong> 只要 IWY 在 BBI 之下，不要去猜底，耐心持有現金。</li>
                </ul>
                
                <p style="font-size: 0.9em; color: #78350f; margin-top: 15px;">* 備註：若遇到乖離率大於 +3% 的「過熱風險」，代表巨頭正在進行最後的趕底噴出，此時請停止加倉，隨時準備迎接均值回歸的修正。</p>
            </div>
        </div>
    </body>
    </html>
    """

    with open('iwy_signal_dashboard.html', 'w', encoding='utf-8') as f:
        f.write(html_content)
    print("Dashboard generated: iwy_signal_dashboard.html")

if __name__ == "__main__":
    generate_report()
