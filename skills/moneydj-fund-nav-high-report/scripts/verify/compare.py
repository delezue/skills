"""Compare the skill's funds.csv with independently obtained data."""
import csv, json, re, sys, time, urllib.request
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor

rows = {r["代碼"]: r for r in csv.DictReader(open("funds.csv", encoding="utf-8-sig"))}
B = json.load(open("browser_data.json", encoding="utf-8"))
code_of = lambda href: re.search(r"A=([^&]+)", href).group(1)
num = lambda s: None if s in ("", "--", "-", "N/A", None) else float(str(s).replace(",", ""))

# ---- 1. category table: browser-rendered vs CSV -------------------------------------------
PER = ["一日", "一週", "一個月", "三個月", "今年以來", "一年", "三年", "年化標準差"]
bad1, checked1, missing_both = [], 0, 0
for r in B["cat"]:
    c = code_of(r["href"]); s = rows.get(c)
    if s is None: bad1.append((c, "not in CSV")); continue
    if r["name"] != s["名稱"]: bad1.append((c, "name", r["name"], s["名稱"]))
    if not s["日期"].endswith(r["cells"][0]): bad1.append((c, "date", r["cells"][0], s["日期"]))
    for lab, shown in zip(PER, r["cells"][1:9]):
        a, b = num(shown), num(s[lab])
        checked1 += 1
        if a is None and b is None: missing_both += 1; continue
        if a is None or b is None or abs(a - b) > 0.0051:   # page shows 2 decimals
            bad1.append((c, lab, shown, s[lab]))
    # page link == skill link
    if not s["連結"].endswith(r["href"]): bad1.append((c, "link", r["href"], s["連結"]))
print(f"[1] category: browser rows {len(B['cat'])}, CSV rows {len(rows)}, "
      f"cells compared {checked1} (both missing {missing_both}), mismatches {len(bad1)}")
for x in bad1[:10]: print("    ", x)
missing_codes = set(rows) - {code_of(r["href"]) for r in B["cat"]}
print("    in CSV but not on page:", sorted(missing_codes)[:10])

# ---- 2a. sampled fund pages read by browser DOM vs CSV --------------------------------------
LAB = ["淨值日期", "最新淨值", "每日變化", "最高淨值(年)", "最低淨值(年)"]
bad2, n2 = [], 0
for d in B["det"]:
    c = code_of(d["href"]); s = rows[c]
    if d.get("error") or not d.get("values"): bad2.append((c, "browser error", d.get("error"))); continue
    if d["labels"] != LAB: bad2.append((c, "labels", d["labels"]))
    n2 += 1
    vals = dict(zip(LAB, d["values"]))
    if vals["淨值日期"] != s["淨值日期"]: bad2.append((c, "淨值日期", vals["淨值日期"], s["淨值日期"]))
    for lab in ("最新淨值", "最高淨值(年)", "最低淨值(年)", "每日變化"):
        a, b = num(vals[lab]), num(s[lab])
        if (a is None) != (b is None) or (a is not None and abs(a - b) > 1e-9):
            bad2.append((c, lab, vals[lab], s[lab]))
print(f"[2a] fund pages via browser DOM: sampled {n2}, mismatches {len(bad2)}")
for x in bad2[:10]: print("    ", x)

# ---- 2b. every fund page re-parsed with html.parser (not the skill's regex) -----------------
class Cells(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows = []; self.row = None; self.cell = None
    def handle_starttag(self, t, a):
        if t == "tr": self.row = []
        elif t == "td" and self.row is not None: self.cell = ""
    def handle_endtag(self, t):
        if t == "td" and self.cell is not None: self.row.append(self.cell.strip()); self.cell = None
        elif t == "tr" and self.row is not None: self.rows.append(self.row); self.row = None
    def handle_data(self, d):
        if self.cell is not None: self.cell += d

def page(c):
    url = rows[c]["連結"] + "&_=%d" % time.time_ns()
    for i in range(3):
        try:
            raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read()
            p = Cells(); p.feed(raw.decode("cp950", "replace"))
            for i_, r in enumerate(p.rows):
                if r[:2] == ["淨值日期", "最新淨值"]:
                    return c, dict(zip(r, p.rows[i_ + 1]))
            return c, None
        except Exception as e:
            time.sleep(2)
    return c, "ERR"

with ThreadPoolExecutor(4) as ex:
    res = list(ex.map(page, rows))
bad3, nap = [], 0
for c, v in res:
    s = rows[c]
    if v in (None, "ERR"): bad3.append((c, v)); continue
    for lab in ("淨值日期", "最新淨值", "最高淨值(年)", "最低淨值(年)"):
        a, b = v.get(lab, ""), s[lab]
        if lab == "淨值日期":
            if a != b: bad3.append((c, lab, a, b))
        else:
            x, y = num(a), num(b)
            if (x is None) != (y is None) or (x is not None and abs(x - y) > 1e-9): bad3.append((c, lab, a, b))
    if v.get("最新淨值") == "N/A": nap += 1
print(f"[2b] all fund pages via html.parser: {len(res)} pages, N/A pages {nap}, mismatches {len(bad3)}")
for x in bad3[:10]: print("    ", x)

# ---- 3. formula and plausibility ------------------------------------------------------------
bad4, n4 = [], 0
for c, s in rows.items():
    nav, hi, lo, g = num(s["最新淨值"]), num(s["最高淨值(年)"]), num(s["最低淨值(年)"]), num(s["最新淨值與最高淨值差距%"])
    if nav is None:
        if g is not None: bad4.append((c, "gap without NAV"))
        continue
    n4 += 1
    exp = (nav / hi - 1) * 100
    if abs(exp - g) > 1e-9: bad4.append((c, "formula", g, exp))
    if not (lo - 1e-9 <= nav <= hi + 1e-9): bad4.append((c, "outside 1y range", lo, nav, hi))
    if g > 1e-9: bad4.append((c, "gap > 0", g))
print(f"[3] formula + low<=NAV<=high + gap<=0: funds checked {n4}, problems {len(bad4)}")
for x in bad4[:10]: print("    ", x)
