#!/usr/bin/env python3
"""
鉅亨基金歷史淨值 → SQLite（增量）→ ZLEMA 看盤 HTML

用法：
  python fund_zlema_viewer.py A36004 --out report.html
  python fund_zlema_viewer.py https://fund.cnyes.com/detail/安聯台灣科技基金/A36004
  python fund_zlema_viewer.py A36004 --full        # 忽略本地資料，整段重抓

資料來源：
  完整歷史  https://www.anuefund.com/anuefundApi/FundDetail/FundInfo?fundDetailEnum=NavHIS&FundID={code}
            （一次回傳成立以來每日淨值；漲跌幅只到小數 2 位）
  增量更新  https://fund.api.cnyes.com/fund/api/v1/funds/{code}/nav?format=table&page=N
            （每頁 10 筆，新到舊；漲跌幅小數 5 位）
"""

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import relative_strength as rs_mod  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = SKILL_DIR / "data" / "fund_nav.db"
TEMPLATE = SKILL_DIR / "templates" / "viewer_template.html"

ANUE_URL = "https://www.anuefund.com/anuefundApi/FundDetail/FundInfo"
CNYES_URL = "https://fund.api.cnyes.com/fund/api/v1/funds/{code}/nav"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://fund.cnyes.com/",
}
ZLEMA_PERIODS = (13, 21, 55, 200)
TW = timezone(timedelta(hours=8))


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def parse_code(arg):
    """代號或鉅亨網址末段。鉅亨代號有大小寫（如 A1rqsDL），不能一律轉大寫。"""
    s = re.sub(r"[?#].*$", "", arg.strip().strip("<>").rstrip("/"))
    m = re.search(r"([A-Za-z0-9]{5,12})$", s)
    if not m:
        sys.exit(f"看不懂基金代號：{arg}（格式如 A36004、A1rqsDL 或鉅亨基金網址）")
    code = m.group(1)
    return code.upper() if re.fullmatch(r"[A-Za-z]\d{5}", code) else code


def resolve_ids(code):
    """
    鉅亨有兩套代號：fund.cnyes.com 的 cnyes 代號（A36004、A1rqsDL…）與 anuefund 的 FundID（A36004、A49015…）。
    多數國內基金兩者相同；不同時，cnyes 基本資料的 forSaleUrl 帶有 anue 的 FundID。
    回傳 (cnyes_id 或 None, anue_id)。
    """
    try:
        r = requests.get(f"https://fund.api.cnyes.com/fund/api/v1/funds/{code}", headers=HEADERS, timeout=20)
        items = r.json().get("items") if r.ok else None
    except Exception as e:
        log(f"  cnyes 基本資料失敗：{e}")
        items = None
    if isinstance(items, dict) and items.get("displayName"):
        m = re.search(r"FundID=([A-Za-z0-9]+)", items.get("forSaleUrl") or "")
        return code, (m.group(1) if m else code)
    return None, code   # cnyes 查無此代號 → 當成 anue FundID，增量也改用 anue


# ─────────────────────────── SQLite ───────────────────────────

def get_db(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS nav (
            code TEXT NOT NULL, date TEXT NOT NULL, nav REAL NOT NULL,
            change REAL, change_pct REAL, source TEXT,
            PRIMARY KEY (code, date));
        CREATE TABLE IF NOT EXISTS fund_info (
            code TEXT PRIMARY KEY, name TEXT, currency TEXT, company TEXT,
            category TEXT, risk TEXT, launch_date TEXT, updated_at TEXT);
    """)
    return conn


def upsert(conn, code, rows, source):
    conn.executemany(
        "INSERT INTO nav(code,date,nav,change,change_pct,source) VALUES(?,?,?,?,?,?) "
        "ON CONFLICT(code,date) DO UPDATE SET nav=excluded.nav, change=excluded.change, "
        "change_pct=excluded.change_pct, source=excluded.source",
        [(code, r["date"], r["nav"], r["change"], r["change_pct"], source) for r in rows])
    conn.commit()


def load_rows(conn, code):
    cur = conn.execute("SELECT date,nav,change,change_pct FROM nav WHERE code=? ORDER BY date", (code,))
    return [{"date": d, "nav": n, "change": c, "change_pct": p} for d, n, c, p in cur]


# ─────────────────────────── 爬蟲 ───────────────────────────

def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def fetch_anue_full(code):
    """一次抓成立以來全部淨值 + 基本資料。"""
    r = requests.get(ANUE_URL, params={"fundDetailEnum": "NavHIS", "FundID": code},
                     headers=HEADERS, timeout=60)
    r.raise_for_status()
    data = (r.json() or {}).get("data") or {}
    rows = []
    for rec in data.get("navHIS") or []:
        nav = _f(rec.get("nav"))
        if nav is None or nav <= 0:
            continue
        rows.append({"date": str(rec.get("navDate", ""))[:10], "nav": nav,
                     "change": _f(rec.get("upDown")), "change_pct": _f(rec.get("upDownRate"))})
    h = data.get("hearder") or {}   # 鉅亨 API 的拼字就是 hearder
    info = {"name": h.get("fundName"), "currency": h.get("ccy"), "company": h.get("company"),
            "category": h.get("lippertW2_CHI"), "risk": h.get("risklevel"),
            "launch_date": str(h.get("launchdate") or "")[:10] or None}
    return rows, info


def fetch_cnyes_page(code, page):
    r = requests.get(CNYES_URL.format(code=code), params={"format": "table", "page": page},
                     headers=HEADERS, timeout=20)
    r.raise_for_status()
    items = r.json().get("items") or {}
    rows = []
    for rec in items.get("data") or []:
        d = datetime.fromtimestamp(rec["tradeDate"], tz=TW).strftime("%Y-%m-%d")
        rows.append({"date": d, "nav": rec.get("nav"), "change": rec.get("change"),
                     "change_pct": rec.get("changePercent")})
    return rows, items.get("last_page") or 1


def fetch_incremental(code, last_date, max_pages=60):
    """從最新頁往回翻，遇到本地已有日期就停（含最後一筆，用來核對）。"""
    out = []
    page, last_page = 1, 1
    while page <= min(last_page, max_pages):
        rows, last_page = fetch_cnyes_page(code, page)
        if not rows:
            break
        out.extend(rows)
        if rows[-1]["date"] <= last_date:
            break
        page += 1
    else:
        return None  # 斷層太大，交給完整重抓
    return out


def sync(conn, code, cnyes_id, anue_id, full=False):
    cached = load_rows(conn, code)
    have_info = conn.execute("SELECT 1 FROM fund_info WHERE code=?", (code,)).fetchone()
    status = {"cached_before": len(cached), "added": 0, "mode": None, "check": None}

    if cached and not full:
        last = cached[-1]
        log(f"[DB] 本地 {len(cached)} 筆，{cached[0]['date']} ~ {last['date']}，抓最新...")
        try:
            if cnyes_id:
                rows = fetch_incremental(cnyes_id, last["date"])
            else:
                rows = [r for r in fetch_anue_full(anue_id)[0] if r["date"] >= last["date"]]
        except Exception as e:
            log(f"  增量失敗：{e}，改用 anue 完整歷史")
            rows = None
        if rows is not None:
            overlap = next((r for r in rows if r["date"] == last["date"]), None)
            if overlap and abs(overlap["nav"] - last["nav"]) > 1e-6:
                log(f"  ! {last['date']} 本地淨值 {last['nav']} ≠ 網站 {overlap['nav']}，以網站為準")
            status["check"] = {"date": last["date"], "local": last["nav"],
                               "remote": overlap["nav"] if overlap else None}
            new = [r for r in rows if r["date"] >= last["date"]]
            upsert(conn, code, new, "cnyes" if cnyes_id else "anue")
            status["added"] = sum(1 for r in new if r["date"] > last["date"])
            status["mode"] = "incremental"
        else:
            full = True

    if not cached or full:
        log("[API] 下載完整歷史淨值（anuefund NavHIS）...")
        rows, info = fetch_anue_full(anue_id)
        if not rows:
            sys.exit(f"{code}（anue FundID {anue_id}）查無淨值資料，確認代號是否正確")
        before = {r["date"] for r in cached}
        upsert(conn, code, rows, "anue")
        status["added"] = sum(1 for r in rows if r["date"] not in before)
        status["mode"] = "full"
        save_info(conn, code, info)
        # NavHIS 偶爾比 cnyes 晚一天，補抓第一頁
        if cnyes_id:
            try:
                latest, _ = fetch_cnyes_page(cnyes_id, 1)
                upsert(conn, code, latest, "cnyes")
            except Exception as e:
                log(f"  cnyes 第一頁失敗（不影響）：{e}")
    elif not have_info:
        try:
            save_info(conn, code, fetch_anue_full(anue_id)[1])
        except Exception as e:
            log(f"  基本資料失敗（不影響）：{e}")
    return status


def save_info(conn, code, info):
    conn.execute(
        "INSERT OR REPLACE INTO fund_info VALUES(?,?,?,?,?,?,?,?)",
        (code, info.get("name"), info.get("currency"), info.get("company"), info.get("category"),
         info.get("risk"), info.get("launch_date"), datetime.now(TW).isoformat(timespec="seconds")))
    conn.commit()


# ─────────────────────────── 指標 ───────────────────────────

def zlema(values, n):
    """
    Zero-Lag EMA（Ehlers & Way 2010；同 TradingView / pandas_ta zlma）：
      src[t] = 2·x[t] − x[t−lag]，lag = (n−1)//2，ZLEMA = EMA_n(src)，α = 2/(n+1)。
    src 從第 lag 根起才有定義；EMA 以前 n 個 src 的 SMA 起始（TA-Lib / pandas_ta 慣例），
    第一個輸出在第 lag+n−1 根。之前用 x[0] 起始並把 t<lag 的 src 當成 x，ZLEMA200 起始點偏差可達 37%。
    """
    lag = (n - 1) // 2
    a = 2 / (n + 1)
    out = [None] * len(values)
    src = [2 * values[i] - values[i - lag] for i in range(lag, len(values))]
    if len(src) < n:
        return out
    ema = sum(src[:n]) / n
    out[lag + n - 1] = round(ema, 4)
    for k in range(n, len(src)):
        ema = a * src[k] + (1 - a) * ema
        out[lag + k] = round(ema, 4)
    return out


def trading_rows(rows):
    """
    anue NavHIS 早期資料（A32007 在 2015 年以前）每個日曆天都有一筆，週末／假日是前一天淨值的複本。
    這會讓 ZLEMA 把日曆天當交易日。只在「該年超過 300 筆」的年份，去掉週末列與淨值未變且漲跌為 0 的列。
    資料庫保留原始資料，只在計算指標前過濾。
    """
    per_year = {}
    for r in rows:
        per_year[r["date"][:4]] = per_year.get(r["date"][:4], 0) + 1
    out, dropped = [], 0
    for r in rows:
        if per_year[r["date"][:4]] > 300 and out:
            wd = datetime.strptime(r["date"], "%Y-%m-%d").weekday()
            if wd >= 5 or (r["nav"] == out[-1]["nav"] and not r["change"]):
                dropped += 1
                continue
        out.append(r)
    return out, dropped


def build_series(rows):
    navs = [r["nav"] for r in rows]
    z = {n: zlema(navs, n) for n in ZLEMA_PERIODS}
    ytd_high, dd, bias = [], [], []
    cur_year, hi = None, None
    for i, r in enumerate(rows):
        y = r["date"][:4]
        if y != cur_year:
            cur_year, hi = y, r["nav"]
        hi = max(hi, r["nav"])
        ytd_high.append(hi)
        dd.append(round((r["nav"] / hi - 1) * 100, 3))
        z13 = z[13][i]
        bias.append(round((r["nav"] / z13 - 1) * 100, 3) if z13 else None)
    pct = []
    for i, r in enumerate(rows):
        p = r["change_pct"]
        if i > 0:
            calc = (r["nav"] / rows[i - 1]["nav"] - 1) * 100
            # 來源漲跌幅缺值或與淨值對不上（如 A32007 2024-03-18 標 0% 但淨值 +1.73%）時用淨值重算
            if p is None or abs(calc - p) > 0.05:
                p = calc
        pct.append(round(p, 3) if p is not None else None)
    return {"date": [r["date"] for r in rows], "nav": navs, "pct": pct,
            "z13": z[13], "z21": z[21], "z55": z[55], "z200": z[200],
            "ytdHigh": ytd_high, "ddYtd": dd, "bias13": bias}


# ─────────────────────────── main ───────────────────────────

def main():
    ap = argparse.ArgumentParser(description="鉅亨基金淨值 ZLEMA 看盤工具")
    ap.add_argument("fund", help="基金代號（A36004）或鉅亨基金網址")
    ap.add_argument("--out", help="HTML 輸出路徑（預設 ./fund_<code>.html）")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--full", action="store_true", help="忽略本地資料，完整重抓")
    ap.add_argument("--no-rs", action="store_true", help="不計算相對加權指數的強弱（不連證交所）")
    args = ap.parse_args()

    code = parse_code(args.fund)
    conn = get_db(Path(args.db))
    cnyes_id, anue_id = resolve_ids(code)
    if anue_id != code or not cnyes_id:
        log(f"[ID] cnyes {cnyes_id or '—'} → anue FundID {anue_id}")
    status = sync(conn, code, cnyes_id, anue_id, args.full)
    status["cnyes_id"], status["anue_id"] = cnyes_id, anue_id
    rows, status["filled_dropped"] = trading_rows(load_rows(conn, code))
    info_row = conn.execute("SELECT name,currency,company,category,risk,launch_date FROM fund_info WHERE code=?",
                            (code,)).fetchone()
    info = dict(zip(["name", "currency", "company", "category", "risk", "launch_date"], info_row or [None] * 6))
    info["code"] = code
    info["url"] = (f"https://fund.cnyes.com/detail/{info.get('name') or code}/{cnyes_id}" if cnyes_id
                   else f"https://www.anuefund.com/Redr/Redr.aspx?FundID={anue_id}")

    s = build_series(rows)
    last = len(rows) - 1

    rs_stats = None
    if not args.no_rs:
        try:
            rs_mod.init_tables(conn)
            status["tri"] = rs_mod.sync_tri(conn)
            divs = rs_mod.sync_dividends(conn, code, anue_id)
            rs = rs_mod.build_rs(s["date"], s["nav"], divs, rs_mod.load_tri(conn))
            s.update(rs["series"])
            rs_stats = rs["stats"]
        except Exception as e:
            log(f"[RS] 相對強弱計算失敗，報表不含相對強弱：{e}")
    summary = {
        "code": code, "name": info.get("name"), "rows": len(rows),
        "first": rows[0]["date"], "last": rows[last]["date"], "nav": rows[last]["nav"],
        "change_pct": s["pct"][last], "ytd_high": s["ytdHigh"][last], "dd_ytd": s["ddYtd"][last],
        "bias13": s["bias13"][last], **{f"zlema{n}": s[f"z{n}"][last] for n in ZLEMA_PERIODS},
        "rs": rs_stats, "sync": status, "db": str(Path(args.db).resolve()),
    }

    payload = {"info": info, "series": s, "rs": rs_stats,
               "generated": datetime.now(TW).strftime("%Y-%m-%d %H:%M")}
    html = TEMPLATE.read_text(encoding="utf-8")
    title = f"{info.get('name') or code} 淨值看盤"
    html = html.replace("{{TITLE}}", title).replace(
        "{{DATA_JSON}}", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    out = Path(args.out or f"fund_{code}.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    summary["out"] = str(out.resolve())
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
