#!/usr/bin/env python3
"""MoneyDJ fund category -> per-fund NAV vs 1-year high -> HTML comparison report.

Step 1  category table   /JsonData/iQuote/iQuoteJsonData.xdjjson?x=FundAreaFund&a={C}
        (the JSON the page iQuoteFundCatFund.djhtm?A=2&B=1&C={C} loads by XHR)
Step 2  each fund's page  /funddj/ya/yp010000.djhtm?A={code}   (code starts with AC)
                          /funddj/ya/yp010001.djhtm?A={code}   (any other code)
        -> 淨值日期 / 最新淨值 / 每日變化 / 最高淨值(年) / 最低淨值(年)
Step 3  距年高 % = (最新淨值 / 最高淨值(年) - 1) x 100    (0 = at the high, < 0 below it)

Standard library only. Output: HTML report, funds.csv, summary.json.
"""
import argparse
import concurrent.futures as cf
import csv
import datetime as dt
import html
import json
import os
import re
import statistics
import sys
import time
import urllib.request

BASE = "https://www.moneydj.com"
CAT_JSON = BASE + "/JsonData/iQuote/iQuoteJsonData.xdjjson?x=FundAreaFund&a={cat}"
CAT_PAGE = BASE + "/iQuote/iQuoteFundCatFund.djhtm?A=2&B=1&C={cat}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"

# V4..V11 of the category JSON, in the page's column order
PERIODS = [("d1", "一日"), ("w1", "一週"), ("m1", "一個月"), ("m3", "三個月"),
           ("ytd", "今年以來"), ("y1", "一年"), ("y3", "三年"), ("std", "年化標準差")]
NEAR_HIGH_PCT = -1.0   # within 1 % of the 1-year high counts as "near the high"


def fund_url(code):
    page = "yp010000" if code.upper().startswith("AC") else "yp010001"
    return f"{BASE}/funddj/ya/{page}.djhtm?A={code}"


def fresh(url):
    """MoneyDJ serves pages and JSON from several server-side caches that can be up to ~30 min
    (or a whole NAV day) behind; the same URL fetched 8 times returned yesterday's NAV up to 7 times.
    A unique '_' query parameter (what jQuery's cache:false does) always gets a fresh copy."""
    return f"{url}{'&' if '?' in url else '?'}_={time.time_ns()}"


def http_get(url, timeout=30, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(fresh(url), headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # network hiccup / 5xx: back off and retry
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def to_float(s):
    """'' or '--' -> None (missing is not 0: a fund with no 3-year history did not return 0 %)."""
    if s is None:
        return None
    s = str(s).replace(",", "").strip()
    if s in ("", "--", "-", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fetch_category(cat):
    raw = http_get(CAT_JSON.format(cat=cat))
    data = json.loads(raw.decode("utf-8"))["ResultSet"]["Result"]
    rows = []
    for r in data:
        row = {"code": r["V1"], "name": r["V2"], "date": r["V3"], "region": r.get("V12", "")}
        for i, (key, _) in enumerate(PERIODS):
            row[key] = to_float(r.get(f"V{4 + i}"))
        rows.append(row)
    return rows


NAV_TABLE = re.compile(r"淨值日期.*?</tr>(.*?)</tr>", re.S)
TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S)


def parse_nav(page_html):
    """The fund page has one table whose header row is 淨值日期/最新淨值/每日變化/最高淨值(年)/最低淨值(年);
    the values are in the next <tr>."""
    m = NAV_TABLE.search(page_html)
    if not m:
        return None
    cells = [re.sub(r"<[^>]+>", "", c).strip() for c in TD.findall(m.group(1))]
    if len(cells) < 5:
        return None
    return {"nav_date": cells[0], "nav": to_float(cells[1]), "nav_chg": to_float(cells[2]),
            "nav_high": to_float(cells[3]), "nav_low": to_float(cells[4])}


def fetch_detail(code, delay, cat_date="", tries=3):
    """Fetch the fund page; if its NAV date is still older than the category table's date
    (a stale copy got through), fetch again and keep the newest."""
    best = None
    for _ in range(tries):
        time.sleep(delay)
        raw = http_get(fund_url(code))
        d = parse_nav(raw.decode("cp950", "replace"))   # pages are Big5; cp950 is its superset
        if d is None:
            return best
        if best is None or (d["nav_date"] or "") > (best["nav_date"] or ""):
            best = d
        if not cat_date or (best["nav_date"] or "") >= cat_date:
            break
    return best


def pct_from_high(nav, high):
    if nav is None or high is None or high <= 0:
        return None
    return (nav / high - 1.0) * 100.0


def enrich(rows, workers, delay, cache_dir):
    cache = {}
    # one cache file per day: a rerun the same day skips pages already fetched,
    # a run on another day never reuses old NAVs
    today = dt.date.today().strftime("%Y%m%d")
    cache_file = os.path.join(cache_dir, f"detail_cache_{today}.json") if cache_dir else None
    if cache_file and os.path.exists(cache_file):
        try:
            with open(cache_file, encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            cache = {}
    cat_date = {r["code"]: r["date"] for r in rows}
    # refetch a cached page if the category table now has a newer date than the cached NAV
    todo = [r["code"] for r in rows
            if r["code"] not in cache or (cache[r["code"]].get("nav_date") or "") < r["date"]]
    failed = []
    if todo:
        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(fetch_detail, c, delay, cat_date[c]): c for c in todo}
            for n, fut in enumerate(cf.as_completed(futs), 1):
                c = futs[fut]
                try:
                    d = fut.result()
                    if d is None:
                        failed.append(c)
                    else:
                        cache[c] = d
                except Exception as e:
                    failed.append(c)
                    print(f"  ! {c}: {e}", file=sys.stderr)
                if n % 25 == 0 or n == len(todo):
                    print(f"  detail pages {n}/{len(todo)}", file=sys.stderr)
        if cache_file:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
    for r in rows:
        d = cache.get(r["code"]) or {}
        r.update({k: d.get(k) for k in ("nav_date", "nav", "nav_chg", "nav_high", "nav_low")})
        r["gap_high"] = pct_from_high(r["nav"], r["nav_high"])
        r["url"] = fund_url(r["code"])
    return failed


def summarize(rows, cat, failed):
    gaps = [r["gap_high"] for r in rows if r["gap_high"] is not None]
    with_gap = [r for r in rows if r["gap_high"] is not None]
    def top(key, n=5, reverse=True):
        xs = [r for r in rows if r.get(key) is not None]
        xs.sort(key=lambda r: r[key], reverse=reverse)
        return [{"code": r["code"], "name": r["name"], key: r[key]} for r in xs[:n]]
    return {
        "category": cat,
        "region": rows[0]["region"] if rows else "",
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "n_funds": len(rows),
        "n_with_nav": len(with_gap),
        "n_failed": len(failed),
        "failed_codes": failed,
        "latest_date": max((r["date"] for r in rows if r["date"]), default=""),
        "median_gap_high": statistics.median(gaps) if gaps else None,
        "n_near_high": sum(1 for g in gaps if g >= NEAR_HIGH_PCT),
        "n_below_10": sum(1 for g in gaps if g <= -10),
        "near_high_threshold_pct": NEAR_HIGH_PCT,
        "closest_to_high": top("gap_high", reverse=True),
        "furthest_from_high": top("gap_high", reverse=False),
        "best_ytd": top("ytd"),
        "best_y1": top("y1"),
    }


def write_csv(rows, path):
    cols = ["code", "name", "date"] + [k for k, _ in PERIODS] + \
           ["nav_date", "nav", "nav_chg", "nav_high", "nav_low", "gap_high", "url"]
    head = ["代碼", "名稱", "日期"] + [lab for _, lab in PERIODS] + \
           ["淨值日期", "最新淨值", "每日變化", "最高淨值(年)", "最低淨值(年)", "最新淨值與最高淨值差距%", "連結"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:   # BOM so Excel reads the Chinese
        w = csv.writer(f)
        w.writerow(head)
        for r in rows:
            w.writerow(["" if r.get(c) is None else r.get(c) for c in cols])


def render_html(rows, summary, template_path, out_path, cat):
    with open(template_path, encoding="utf-8") as f:
        tpl = f.read()
    payload = {"summary": summary, "rows": rows, "source": CAT_PAGE.format(cat=cat),
               "periods": PERIODS}
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    region = summary.get("region") or f"類別 {cat}"
    out = (tpl.replace("{{TITLE}}", html.escape(f"{region}基金 淨值距年高"))
              .replace("{{DATA_JSON}}", data))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--category", default="47", help="MoneyDJ C= id (47 = 台灣)")
    ap.add_argument("--out", required=True, help="output HTML path")
    ap.add_argument("--out-dir", help="folder for funds.csv / summary.json / cache (default: next to --out)")
    ap.add_argument("--workers", type=int, default=4, help="parallel detail-page fetches (be polite: <= 6)")
    ap.add_argument("--delay", type=float, default=0.2, help="seconds each worker waits before a request")
    ap.add_argument("--limit", type=int, default=0, help="only the first N funds (for a quick test)")
    ap.add_argument("--match", default="", help="keep only funds whose name contains any of these comma-separated words")
    ap.add_argument("--no-cache", action="store_true", help="refetch every detail page")
    ap.add_argument("--template", default=os.path.join(here, "..", "templates", "report_template.html"))
    a = ap.parse_args()

    out_dir = a.out_dir or os.path.dirname(os.path.abspath(a.out))
    os.makedirs(out_dir, exist_ok=True)

    print(f"category {a.category}: fetching fund list", file=sys.stderr)
    rows = fetch_category(a.category)
    if a.match:
        words = [w.strip() for w in a.match.split(",") if w.strip()]
        rows = [r for r in rows if any(w in r["name"] for w in words)]
    if a.limit:
        rows = rows[:a.limit]
    print(f"  {len(rows)} funds", file=sys.stderr)
    if not rows:
        sys.exit("no funds found: check --category / --match")

    failed = enrich(rows, a.workers, a.delay, None if a.no_cache else out_dir)
    rows.sort(key=lambda r: (r["gap_high"] is None, -(r["gap_high"] or 0)))   # closest to the high first

    summary = summarize(rows, a.category, failed)
    write_csv(rows, os.path.join(out_dir, "funds.csv"))
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    render_html(rows, summary, os.path.normpath(a.template), a.out, a.category)
    print(json.dumps({k: summary[k] for k in ("n_funds", "n_with_nav", "n_failed", "latest_date",
                                              "median_gap_high", "n_near_high", "n_below_10")},
                     ensure_ascii=False))
    print(f"HTML -> {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
