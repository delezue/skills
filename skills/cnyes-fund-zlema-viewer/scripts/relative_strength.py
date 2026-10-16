"""
相對強弱：基金「含息總報酬」 vs 臺灣證交所「發行量加權股價報酬指數」（含息 TAIEX，2003-01 起）。

兩邊都要含息才公平：
- 累積型基金淨值本身含息；一般加權指數（^TWII）不含息，每年少約 3–4 個百分點，直接比會讓基金看起來偏強。
- 配息型基金淨值不含已配出的錢，所以基金端用 anue 配息紀錄在除息日把配息再投入，還原總報酬。
"""

import sys
import time
from datetime import date, datetime

import requests

TRI_URL = "https://www.twse.com.tw/rwd/zh/TAIEX/MFI94U"
DIV_URL = "https://www.anuefund.com/anuefundApi/FundDetail/FundInfo"
TRI_START = (2020, 1)   # 使用者指定（2026-10-16）：大盤含息指數只抓 2020-01-01 起；證交所最早到 2003-01
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
EXCESS_WINDOWS = (20, 60, 120, 250)


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def init_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS bench_tri (date TEXT PRIMARY KEY, value REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS dividend (
            code TEXT NOT NULL, ex_date TEXT NOT NULL, amount REAL NOT NULL,
            PRIMARY KEY (code, ex_date));
    """)


# ─────────────────────────── 含息加權指數 ───────────────────────────

def _roc_to_iso(s):
    y, m, d = s.strip().split("/")
    return f"{int(y) + 1911:04d}-{int(m):02d}-{int(d):02d}"


def _fetch_tri_month(y, m):
    for attempt in range(4):
        try:
            r = requests.get(TRI_URL, params={"date": f"{y}{m:02d}01", "response": "json"},
                             headers=HEADERS, timeout=20)
            j = r.json()
            if j.get("stat") == "OK":
                return [(_roc_to_iso(d), float(v.replace(",", ""))) for d, v in j.get("data") or []]
            if "沒有符合" in str(j.get("stat")):
                return []
            raise RuntimeError(j.get("stat"))
        except Exception as e:
            wait = 5 * (attempt + 1)
            log(f"    TWSE {y}-{m:02d} 失敗（{e}），{wait} 秒後重試")
            time.sleep(wait)
    raise RuntimeError(f"TWSE 報酬指數 {y}-{m:02d} 連續失敗")


def sync_tri(conn):
    """
    每月一次請求。已有資料的過去月份跳過；最近兩個月每次重抓（當月還在增加）。
    2020-01 起約 82 個月，第一次約 1 分鐘；之後只抓 1–2 次。起始日之前的舊資料從資料庫刪掉。
    """
    start = f"{TRI_START[0]:04d}-{TRI_START[1]:02d}-01"
    conn.execute("DELETE FROM bench_tri WHERE date < ?", (start,))
    conn.commit()
    today = date.today()
    have = {r[0] for r in conn.execute("SELECT DISTINCT substr(date,1,7) FROM bench_tri")}
    months = []
    y, m = TRI_START
    while (y, m) <= (today.year, today.month):
        recent = (today.year * 12 + today.month) - (y * 12 + m) <= 1
        if recent or f"{y:04d}-{m:02d}" not in have:
            months.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    if len(months) > 3:
        log(f"[TRI] 下載含息加權報酬指數 {len(months)} 個月（第一次較久，之後只補最新）...")
    added = 0
    for i, (y, m) in enumerate(months, 1):
        rows = _fetch_tri_month(y, m)
        cur = conn.executemany("INSERT OR REPLACE INTO bench_tri VALUES(?,?)", rows)
        added += len(rows)
        conn.commit()
        if len(months) > 3 and i % 40 == 0:
            log(f"    {i}/{len(months)}")
        time.sleep(0.5)
    n, last = conn.execute("SELECT count(*), max(date) FROM bench_tri").fetchone()
    return {"months_fetched": len(months), "rows": n, "last": last}


def load_tri(conn):
    start = f"{TRI_START[0]:04d}-{TRI_START[1]:02d}-01"
    return dict(conn.execute("SELECT date, value FROM bench_tri WHERE date >= ?", (start,)))


# ─────────────────────────── 配息 ───────────────────────────

def sync_dividends(conn, code, anue_id):
    try:
        r = requests.get(DIV_URL, params={"fundDetailEnum": "DividendHIS", "FundID": anue_id},
                         headers=HEADERS, timeout=30)
        recs = ((r.json() or {}).get("data") or {}).get("dividendHIS") or []
    except Exception as e:
        log(f"  配息紀錄失敗（以本地資料計算）：{e}")
        recs = []
    rows = []
    for x in recs:
        try:
            amt = float(x.get("totalDistribution") or 0)
        except ValueError:
            continue
        d = str(x.get("excludingDate") or "")[:10]
        if amt > 0 and d:
            rows.append((code, d, amt))
    conn.executemany("INSERT OR REPLACE INTO dividend VALUES(?,?,?)", rows)
    conn.commit()
    return sorted((d, a) for d, a in conn.execute(
        "SELECT ex_date, amount FROM dividend WHERE code=?", (code,)))


# ─────────────────────────── 計算 ───────────────────────────

def total_return(dates, navs, divs):
    """除息日（或之後第一個有淨值的日子）以當日淨值把配息再投入：份額 × (1 + 配息 ÷ 除息日淨值)。"""
    factor, j, out, applied = 1.0, 0, [], []
    for d, nav in zip(dates, navs):
        while j < len(divs) and divs[j][0] <= d:
            factor *= 1 + divs[j][1] / nav
            applied.append(divs[j][0])
            j += 1
        out.append(nav * factor)
    return out, applied


def build_rs(dates, navs, divs, tri):
    tr, applied = total_return(dates, navs, divs)
    # 基金淨值日對齊報酬指數：同日優先，否則沿用前一個指數日的值（最多隔 7 個日曆天，避免跨長假或資料缺口誤配）
    tri_dates = sorted(tri)
    k, bench = 0, []
    for d in dates:
        while k < len(tri_dates) and tri_dates[k] <= d:
            k += 1
        prev = tri_dates[k - 1] if k else None
        bench.append(tri[prev] if _gap_ok(prev, d) else None)

    ratio = [t / b if b else None for t, b in zip(tr, bench)]

    # Mansfield RS：RS ÷ 250 日均線 − 1（> 0 表示相對大盤的趨勢向上）
    mrs, win, ssum = [], [], 0.0
    for r in ratio:
        if r is None:
            win, ssum = [], 0.0
            mrs.append(None)
            continue
        win.append(r)
        ssum += r
        if len(win) > 250:
            ssum -= win.pop(0)
        mrs.append(round((r / (ssum / len(win)) - 1) * 100, 3) if len(win) == 250 else None)

    n = len(dates) - 1
    excess = {}
    for w in EXCESS_WINDOWS:
        if n - w >= 0 and bench[n] and bench[n - w]:
            f = (tr[n] / tr[n - w] - 1) * 100
            b = (bench[n] / bench[n - w] - 1) * 100
            excess[w] = {"fund": round(f, 2), "bench": round(b, 2), "excess": round(f - b, 2)}

    # 60 日 β：基金日報酬對大盤日報酬的迴歸斜率
    beta = None
    pairs = [((tr[i] / tr[i - 1] - 1), (bench[i] / bench[i - 1] - 1))
             for i in range(max(1, n - 59), n + 1) if bench[i] and bench[i - 1]]
    if len(pairs) >= 40:
        mf = sum(p[0] for p in pairs) / len(pairs)
        mb = sum(p[1] for p in pairs) / len(pairs)
        cov = sum((p[0] - mf) * (p[1] - mb) for p in pairs)
        var = sum((p[1] - mb) ** 2 for p in pairs)
        beta = round(cov / var, 2) if var else None

    valid = [r for r in ratio[-250:] if r is not None]
    rs_high = bool(valid) and ratio[n] is not None and ratio[n] >= max(valid) * 0.999

    return {
        "series": {"tr": [round(x, 4) for x in tr], "tri": bench,
                   "rs": [round(r, 8) if r else None for r in ratio], "mrs": mrs},
        "stats": {"excess": excess, "beta60": beta, "mrs": mrs[n], "rs_52w_high": rs_high,
                  "dividends_applied": len(applied),
                  "first_date": next((d for d, b in zip(dates, bench) if b), None)},
    }


def _gap_ok(tri_date, fund_date):
    if tri_date is None:
        return False
    a = datetime.strptime(tri_date, "%Y-%m-%d")
    b = datetime.strptime(fund_date, "%Y-%m-%d")
    return (b - a).days <= 7
