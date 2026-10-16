#!/usr/bin/env python3
"""
基金即時預估（改寫自 _tmp/fun_nav.py）
MoneyDJ 前 N 大成分股（名稱+比例）→ TWSE/TPEX 名稱對代號 → Fugle 即時報價
→ 權重 × 漲跌幅 加總推估基金當日漲跌 → HTML 報表 + summary.json。

用法：
  python fund_estimate.py --out report.html
  python fund_estimate.py --funds ACDD04:台科,ACFH15:復華 --top-n 10
"""

import argparse
import html as htmlmod
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
import urllib3
from bs4 import BeautifulSoup
from fugle_marketdata import RestClient

# TPEX 憑證鏈缺中繼憑證（對方設定問題），只對公開唯讀 API 停用驗證
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SKILL_DIR = Path(__file__).resolve().parent.parent
MONEYDJ_URL = "https://www.moneydj.com/funddj/yp/yp013000.djhtm?a={code}"
TWSE_API = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_API = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
BENCHMARK = ("IX0001", "加權指數")

MONEYDJ_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8",
    "Referer": "https://www.moneydj.com/",
}


def log(msg):
    print(msg, file=sys.stderr, flush=True)


# ═══════════════════════════════════════════════════════════════════
# Step 0 — 股票名稱 → 代號
# ═══════════════════════════════════════════════════════════════════

def build_name_map() -> dict:
    name_map = {}
    try:
        for item in requests.get(TWSE_API, timeout=20).json():
            code, abbr = item.get("公司代號", "").strip(), item.get("公司簡稱", "").strip()
            if code and abbr:
                name_map[abbr] = code
    except Exception as e:
        log(f"  [WARN] TWSE API 失敗：{e}")
    try:
        for item in requests.get(TPEX_API, timeout=20, verify=False).json():
            code = item.get("SecuritiesCompanyCode", "").strip()
            abbr = item.get("CompanyAbbreviation", "").strip()
            if code and abbr:
                name_map[abbr] = code
    except Exception as e:
        log(f"  [WARN] TPEX API 失敗：{e}")
    return name_map


def resolve_code(name: str, name_map: dict):
    """先完全比對；不行再用前綴比對（簡稱至少 2 字），取最長的簡稱，避免短簡稱誤配。"""
    if name in name_map:
        return name_map[name]
    clean = re.sub(r"[\s\-－]*(KY|＊|\*)$", "", name).strip()
    if clean in name_map:
        return name_map[clean]
    cands = [(abbr, c) for abbr, c in name_map.items()
             if len(abbr) >= 2 and (clean.startswith(abbr) or abbr.startswith(clean))]
    if cands:
        return max(cands, key=lambda t: len(t[0]))[1]
    return None


# ═══════════════════════════════════════════════════════════════════
# Step 1 — MoneyDJ 持股
# ═══════════════════════════════════════════════════════════════════

def scrape_fund_holdings(session, code, nickname, top_n) -> dict:
    url = MONEYDJ_URL.format(code=code)
    result = {"code": code, "nickname": nickname, "full_name": nickname, "url": url,
              "holdings_date": None, "holdings": [], "error": None}
    try:
        # &_= 時間戳繞過 MoneyDJ 伺服器端舊快取（見 moneydj-fund-nav-high-report 陷阱 0）
        resp = session.get(f"{url}&_={int(time.time() * 1000)}", timeout=20)
        resp.raise_for_status()
        raw = resp.content
        text = None
        for enc in ("utf-8", "cp950", "big5"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = raw.decode("utf-8", errors="replace")
        soup = BeautifulSoup(text, "html.parser")

        title_tag = soup.find("title")
        if title_tag:
            head = title_tag.get_text(strip=True).split("-")[0].strip()
            if head:
                result["full_name"] = head

        date_re = re.compile(r"資料月份[：:]\s*(\d{4}[/\-]\d{1,2}[/\-]\d{1,2})")
        for s in soup.stripped_strings:
            m = date_re.search(s)
            if m:
                result["holdings_date"] = m.group(1)
                break

        holdings = _parse_holdings(soup)
        holdings.sort(key=lambda h: h["weight_pct"], reverse=True)
        result["holdings"] = holdings[:top_n]
        if not result["holdings"]:
            result["error"] = "未找到成分股（頁面無資料或結構已變）"
    except requests.RequestException as e:
        result["error"] = f"連線失敗：{e}"
    except Exception as e:
        result["error"] = f"解析錯誤：{e}"
    return result


def _parse_holdings(soup) -> list:
    """yp013000 持股表：table.t01，標頭 投資名稱|投資(千股)|比例|增減 ×2（左右兩組）。"""
    pct_re = re.compile(r"^\d+\.?\d*$")
    for table in soup.find_all("table", class_="t01"):
        rows = table.find_all("tr", recursive=False)
        hdr_row = None
        for row in rows:
            t = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
            if "投資名稱" in t and "比例" in t:
                hdr_row = row
                break
        if hdr_row is None:
            continue
        headers = [c.get_text(strip=True) for c in hdr_row.find_all(["th", "td"])]
        name_cols = [i for i, h in enumerate(headers) if "投資名稱" in h]
        pct_cols = [i for i, h in enumerate(headers) if "比例" in h]
        pairs = list(zip(name_cols, pct_cols)) or [(0, 2), (4, 6)]

        holdings = []
        for row in rows:
            if row is hdr_row:
                continue
            cells = [c.get_text(strip=True) for c in row.find_all("td")]
            if len(cells) < 4:
                continue
            for nc, pc in pairs:
                if nc >= len(cells) or pc >= len(cells):
                    continue
                name, pct_s = cells[nc].strip(), cells[pc].strip()
                if not name or name in ("投資名稱", "—", "-"):
                    continue
                if pct_re.match(pct_s):
                    pct = float(pct_s)
                    if 0 < pct <= 100:
                        holdings.append({"name": name, "code": None, "weight_pct": pct,
                                         "weight": pct / 100, "current_price": None,
                                         "prev_close": None, "change_pct": None,
                                         "contribution_pct": None})
        if holdings:
            return holdings
    return []


# ═══════════════════════════════════════════════════════════════════
# Step 3 — Fugle 即時報價
# ═══════════════════════════════════════════════════════════════════

def fetch_quote(client, symbol):
    data = client.stock.intraday.quote(symbol=symbol)
    if not data or not isinstance(data, dict) or data.get("statusCode"):
        raise RuntimeError(data.get("message") if isinstance(data, dict) else "無資料")
    close_p = data.get("closePrice") or data.get("lastPrice") or data.get("price") or 0
    prev_p = data.get("previousClose") or data.get("referencePrice") or 0
    chg = data.get("changePercent")
    if chg is None and prev_p and close_p:
        chg = (float(close_p) - float(prev_p)) / float(prev_p) * 100
    return {"name": data.get("name", symbol),
            "current": float(close_p) if close_p else None,
            "prev_close": float(prev_p) if prev_p else None,
            "change_pct": round(float(chg), 2) if chg is not None else None,
            "date": data.get("date"),
            "updated": data.get("lastUpdated")}


def fetch_all_quotes(client, symbols) -> dict:
    quotes = {}
    for i, sym in enumerate(symbols, 1):
        try:
            quotes[sym] = fetch_quote(client, sym)
        except Exception as e:
            log(f"    [{i}/{len(symbols)}] {sym} 取價失敗：{e}")
        time.sleep(0.2)
    return quotes


# ═══════════════════════════════════════════════════════════════════
# Step 4 — 推估
# ═══════════════════════════════════════════════════════════════════

def estimate_fund(fund, quotes):
    """
    est_change_pct：前 N 大持股「原始權重 × 漲跌幅」加總（不正規化）＝ 前 N 大的貢獻，
                    覆蓋率越低越偏離真實漲跌。
    scaled_change_pct：est / 覆蓋率，假設其餘持股與前 N 大同漲跌的放大值。
    """
    wsum = cov = 0.0
    for h in fund["holdings"]:
        q = quotes.get(h.get("code") or "")
        if not q:
            continue
        h["current_price"], h["prev_close"], h["change_pct"] = q["current"], q["prev_close"], q["change_pct"]
        if q["change_pct"] is not None:
            c = h["weight"] * q["change_pct"]
            h["contribution_pct"] = round(c, 4)
            wsum += c
            cov += h["weight"]
    fund["est_change_pct"] = round(wsum, 3) if cov > 0 else None
    fund["scaled_change_pct"] = round(wsum / cov, 3) if cov > 0 else None
    fund["covered_weight_pct"] = round(cov * 100, 1)
    fund["top_weight_pct"] = round(sum(h["weight_pct"] for h in fund["holdings"]), 1)
    return fund


# ═══════════════════════════════════════════════════════════════════
# Step 5 — HTML（artifact 規範：無 doctype、顏色全 token、深淺色；台股紅漲綠跌）
# ═══════════════════════════════════════════════════════════════════

E = htmlmod.escape


def _cls(p):
    if p is None:
        return "na"
    return "up" if p > 0 else ("down" if p < 0 else "flat")


def _fmt(p, d=2, unit="%"):
    if p is None:
        return "—"
    return f"{'+' if p > 0 else ''}{p:.{d}f}{unit}"


def _price(p):
    return "—" if not p else f"{p:,.2f}"


CSS = """
/* 版面：頂部摘要（大盤 + 排名條形圖）→ 各基金持股卡片網格 */
:root{
  --bg:#f3f4f7; --surface:#ffffff; --surface-2:#f7f8fb; --line:#e3e6ee;
  --fg:#1b2130; --muted:#6a7183; --faint:#9aa1b2;
  --accent:#2d5bd7;
  --up:#d42b2b; --up-bg:#fdecec; --down:#138a46; --down-bg:#e7f5ec; --flat:#5a6274;
  --warn:#a15c00; --warn-bg:#fff4e0;
  --sans:"Noto Sans TC","PingFang TC","Microsoft JhengHei",system-ui,sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,Consolas,monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#12151c; --surface:#1a1f29; --surface-2:#202633; --line:#2c3341;
  --fg:#e6e9f0; --muted:#9aa2b4; --faint:#6b7386; --accent:#7f9cf5;
  --up:#ff6b6b; --up-bg:#3a1f22; --down:#3ecf7a; --down-bg:#17322a; --flat:#a0a8ba;
  --warn:#f0b35a; --warn-bg:#3a2e17; color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#12151c; --surface:#1a1f29; --surface-2:#202633; --line:#2c3341;
  --fg:#e6e9f0; --muted:#9aa2b4; --faint:#6b7386; --accent:#7f9cf5;
  --up:#ff6b6b; --up-bg:#3a1f22; --down:#3ecf7a; --down-bg:#17322a; --flat:#a0a8ba;
  --warn:#f0b35a; --warn-bg:#3a2e17; color-scheme:dark}
*,*::before,*::after{box-sizing:border-box}
body{background:var(--bg);color:var(--fg);font-family:var(--sans);font-size:14px;line-height:1.5;
  padding-block:24px 40px;padding-left:max(16px,env(safe-area-inset-left,0px));
  padding-right:max(16px,env(safe-area-inset-right,0px))}
.wrap{max-width:1360px;margin:0 auto;display:flex;flex-direction:column;gap:20px}
a{color:var(--accent);text-decoration:none} a:hover{text-decoration:underline}
.num{font-family:var(--mono);font-variant-numeric:tabular-nums}
header h1{margin:0;font-size:1.6rem;font-weight:800;letter-spacing:-.01em;text-wrap:balance}
header .meta{margin-top:4px;color:var(--muted);font-size:.82rem}
.note{background:var(--warn-bg);color:var(--warn);border-radius:8px;padding:8px 12px;font-size:.8rem;max-width:80ch}
.top{display:grid;grid-template-columns:minmax(0,260px) minmax(0,1fr);gap:16px}
@media(max-width:720px){.top{grid-template-columns:minmax(0,1fr)}}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px;min-width:0}
.panel h2{margin:0 0 10px;font-size:.78rem;font-weight:700;color:var(--muted);letter-spacing:.06em}
.bench .big{font-size:2rem;font-weight:800;line-height:1.1}
.bench .sub{color:var(--muted);font-size:.8rem;margin-top:6px}
.rank{overflow-x:auto}
.rank table{width:100%;border-collapse:collapse;min-width:520px}
.rank th{font-size:.72rem;color:var(--muted);text-align:right;font-weight:600;padding:4px 8px;border-bottom:1px solid var(--line)}
.rank th:nth-child(-n+2){text-align:left}
.rank td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
.rank td:nth-child(-n+2){text-align:left}
.rank tr:last-child td{border-bottom:none}
.rank .rk{color:var(--faint);width:28px}
.barcell{width:38%;min-width:140px}
.bar{position:relative;height:10px;background:var(--surface-2);border-radius:2px}
.bar .mid{position:absolute;left:50%;top:-3px;bottom:-3px;width:1px;background:var(--faint)}
.bar span{position:absolute;top:0;bottom:0;border-radius:2px}
.bar span.up{background:var(--up)} .bar span.down{background:var(--down)}
.up{color:var(--up)} .down{color:var(--down)} .flat{color:var(--flat)} .na{color:var(--faint)}
.strong{font-weight:800}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,460px),1fr));gap:16px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;overflow:hidden;min-width:0}
.card .hd{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;padding:14px 16px;border-bottom:1px solid var(--line)}
.card .hd.up{background:var(--up-bg)} .card .hd.down{background:var(--down-bg)}
.card .nick{font-size:1.15rem;font-weight:800}
.card .fname{color:var(--muted);font-size:.74rem;margin-top:2px;overflow-wrap:anywhere}
.card .est{text-align:right;flex-shrink:0}
.card .est .v{font-size:1.5rem;font-weight:800;line-height:1.1}
.card .est .s{font-size:.72rem;color:var(--muted);margin-top:2px}
.tbl{overflow-x:auto}
.tbl table{width:100%;border-collapse:collapse;font-size:.82rem}
.tbl th{font-size:.7rem;color:var(--muted);font-weight:600;text-align:right;padding:6px 10px;background:var(--surface-2);border-bottom:1px solid var(--line)}
.tbl th:nth-child(-n+2){text-align:left}
.tbl td{padding:5px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
.tbl td:nth-child(-n+2){text-align:left}
.tbl tr:last-child td{border-bottom:none}
.tbl td.code{color:var(--accent);font-family:var(--mono)}
.tbl td.miss{color:var(--warn)}
.wbar{display:inline-block;width:44px;height:5px;background:var(--surface-2);border-radius:2px;vertical-align:middle;margin-right:6px;overflow:hidden}
.wbar i{display:block;height:100%;background:var(--accent)}
.empty{text-align:center;color:var(--faint);padding:18px}
footer{color:var(--faint);font-size:.75rem}
"""


def generate_html(funds, bench, generated_at, top_n, quote_date) -> str:
    ranked = sorted(funds, key=lambda f: (f.get("est_change_pct") is None, -(f.get("est_change_pct") or 0)))
    vals = [abs(f["est_change_pct"]) for f in funds if f.get("est_change_pct") is not None]
    scale = max(vals + [0.5])

    rows = ""
    for i, f in enumerate(ranked, 1):
        est = f.get("est_change_pct")
        c = _cls(est)
        bar = ""
        if est is not None:
            w = abs(est) / scale * 50
            pos = f"left:50%;width:{w:.1f}%" if est >= 0 else f"left:{50 - w:.1f}%;width:{w:.1f}%"
            bar = f'<span class="{c}" style="{pos}"></span>'
        rows += (f'<tr><td class="rk num">{i}</td>'
                 f'<td><a href="#f-{E(f["code"])}">{E(f["nickname"])}</a></td>'
                 f'<td class="num strong {c}">{_fmt(est)}</td>'
                 f'<td class="num {_cls(f.get("scaled_change_pct"))}">{_fmt(f.get("scaled_change_pct"))}</td>'
                 f'<td class="num">{f.get("covered_weight_pct", 0):.1f}%</td>'
                 f'<td class="barcell"><div class="bar"><div class="mid"></div>{bar}</div></td></tr>')

    if bench:
        bc = _cls(bench.get("change_pct"))
        bench_html = (f'<div class="big num {bc}">{_fmt(bench.get("change_pct"))}</div>'
                      f'<div class="sub num">{_price(bench.get("current"))}（昨收 {_price(bench.get("prev_close"))}）</div>')
    else:
        bench_html = '<div class="big na">—</div><div class="sub">大盤報價取得失敗</div>'

    cards = ""
    for f in funds:
        est = f.get("est_change_pct")
        c = _cls(est)
        trs = ""
        for h in f["holdings"]:
            chg, con = h.get("change_pct"), h.get("contribution_pct")
            code = h.get("code")
            trs += (f'<tr><td class="code{"" if code else " miss"}">{E(code or "未對應")}</td>'
                    f'<td>{E(h["name"])}</td>'
                    f'<td class="num"><span class="wbar"><i style="width:{min(h["weight_pct"] * 5, 100):.0f}%"></i></span>{h["weight_pct"]:.2f}%</td>'
                    f'<td class="num">{_price(h.get("current_price"))}</td>'
                    f'<td class="num {_cls(chg)}">{_fmt(chg)}</td>'
                    f'<td class="num {_cls(con)}">{_fmt(con, 3, "pp")}</td></tr>')
        if not trs:
            trs = f'<tr><td colspan="6" class="empty">{E(f.get("error") or "無成分股資料")}</td></tr>'
        date_lbl = f"・持股資料 {E(f['holdings_date'])}" if f.get("holdings_date") else ""
        cards += f"""
<section class="card" id="f-{E(f['code'])}">
  <div class="hd {c}">
    <div><div class="nick">{E(f['nickname'])}</div>
      <div class="fname"><a href="{E(f['url'])}" target="_blank" rel="noopener">{E(f['full_name'])}</a>{date_lbl}</div></div>
    <div class="est"><div class="v num {c}">{_fmt(est)}</div>
      <div class="s num">覆蓋 {f.get('covered_weight_pct', 0):.1f}%・放大 {_fmt(f.get('scaled_change_pct'))}</div></div>
  </div>
  <div class="tbl"><table>
    <thead><tr><th>代號</th><th>名稱</th><th>權重</th><th>即時價</th><th>漲跌幅</th><th>貢獻</th></tr></thead>
    <tbody>{trs}</tbody></table></div>
</section>"""

    qd = f"・報價日期 {E(quote_date)}" if quote_date else ""
    return f"""<title>基金即時預估</title>
<meta name="claude:viewport-fit-sides" content="cover">
<style>{CSS}</style>
<div class="wrap">
<header>
  <h1>基金即時預估</h1>
  <div class="meta">產生時間 {E(generated_at)}{qd}・MoneyDJ 前 {top_n} 大持股 × Fugle 即時報價</div>
</header>
<div class="note">推估漲跌 = 前 {top_n} 大持股「權重 × 個股漲跌幅」加總，只涵蓋覆蓋率那部分的基金資產；「放大」= 推估 ÷ 覆蓋率，假設其餘持股與前 {top_n} 大同步。持股為 MoneyDJ 月報資料，不是基金當日實際部位。僅供參考，不代表實際淨值。</div>
<div class="top">
  <div class="panel bench"><h2>{E(BENCHMARK[1])}</h2>{bench_html}</div>
  <div class="panel"><h2>推估漲跌排名</h2><div class="rank"><table>
    <thead><tr><th>#</th><th>基金</th><th>推估</th><th>放大</th><th>覆蓋率</th><th></th></tr></thead>
    <tbody>{rows}</tbody></table></div></div>
</div>
<div class="grid">{cards}</div>
<footer>紅 = 漲、綠 = 跌（台股慣例）。貢獻單位 pp = 對基金漲跌幅的百分點。</footer>
</div>
"""


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

def parse_funds_arg(s):
    out = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.search(r"[?&]a=([A-Za-z0-9]+)", part)
        code_nick = (m.group(1), part) if m else None
        if ":" in part and not m:
            code, nick = part.split(":", 1)
            out.append((code.strip().upper(), nick.strip()))
        elif code_nick:
            out.append((code_nick[0].upper(), code_nick[0].upper()))
        else:
            out.append((part.upper(), part.upper()))
    return out


def main():
    ap = argparse.ArgumentParser(description="基金即時預估")
    ap.add_argument("--config", default=str(SKILL_DIR / "config.json"))
    ap.add_argument("--funds", help="覆蓋 config：CODE:簡稱,CODE:簡稱 或 MoneyDJ 網址")
    ap.add_argument("--add", help="在 config 清單外再加：CODE:簡稱,...")
    ap.add_argument("--top-n", type=int)
    ap.add_argument("--out", default="fund_estimate_report.html")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    funds_list = parse_funds_arg(args.funds) if args.funds else [tuple(x) for x in cfg["funds"]]
    if args.add:
        funds_list += parse_funds_arg(args.add)
    top_n = args.top_n or cfg.get("top_n", 10)
    key_file = SKILL_DIR / "fugle_api_key.txt"
    api_key = (os.environ.get("FUGLE_API_KEY")
               or (key_file.read_text(encoding="utf-8").strip() if key_file.exists() else "")
               or cfg.get("fugle_api_key"))
    if not api_key:
        sys.exit("缺少 Fugle API key：設環境變數 FUGLE_API_KEY，或寫入 skill 資料夾的 fugle_api_key.txt")

    log("[0/4] 建立股票名稱對應表（TWSE + TPEX）...")
    name_map = build_name_map()
    log(f"  -> {len(name_map)} 支")

    log("[1/4] MoneyDJ 成分股...")
    session = requests.Session()
    session.verify = False
    session.headers.update(MONEYDJ_HEADERS)
    funds = []
    for code, nick in funds_list:
        f = scrape_fund_holdings(session, code, nick, top_n)
        log(f"  {nick}({code}): {len(f['holdings'])} 檔" + (f"  ! {f['error']}" if f["error"] else ""))
        funds.append(f)
        time.sleep(1.0)

    log("[2/4] 對應代號...")
    unresolved = set()
    for f in funds:
        for h in f["holdings"]:
            h["code"] = resolve_code(h["name"], name_map)
            if not h["code"]:
                unresolved.add(h["name"])
    if unresolved:
        log(f"  未對應：{', '.join(sorted(unresolved))}")

    symbols = sorted({h["code"] for f in funds for h in f["holdings"] if h.get("code")})
    log(f"[3/4] Fugle 報價 {len(symbols)} 支 + 大盤...")
    client = RestClient(api_key=api_key)
    quotes = fetch_all_quotes(client, symbols)
    try:
        bench = fetch_quote(client, BENCHMARK[0])
    except Exception as e:
        log(f"  大盤取價失敗：{e}")
        bench = None
    dates = sorted({q.get("date") for q in quotes.values() if q.get("date")})
    quote_date = dates[-1] if dates else None

    log("[4/4] 推估...")
    for f in funds:
        estimate_fund(f, quotes)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(generate_html(funds, bench, now, top_n, quote_date), encoding="utf-8")

    summary = {
        "generated_at": now, "quote_date": quote_date, "out": str(out.resolve()),
        "benchmark_change_pct": bench.get("change_pct") if bench else None,
        "n_funds": len(funds), "n_symbols": len(symbols), "n_quotes": len(quotes),
        "unresolved": sorted(unresolved),
        "funds": [{"code": f["code"], "nickname": f["nickname"], "est": f.get("est_change_pct"),
                   "scaled": f.get("scaled_change_pct"), "covered": f.get("covered_weight_pct"),
                   "holdings_date": f.get("holdings_date"), "error": f.get("error")} for f in funds],
    }
    (out.parent / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
