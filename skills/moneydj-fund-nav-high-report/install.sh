#!/usr/bin/env bash
# moneydj-fund-nav-high-report : install into ~/.claude/skills   (macOS / Linux / Git Bash)
#   bash install.sh
set -u
NAME=moneydj-fund-nav-high-report
SRC="$(cd "$(dirname "$0")" && pwd)"
DST="$HOME/.claude/skills/$NAME"

echo; echo "[1/3] Copy skill to $DST"
if [ "$SRC" = "$DST" ]; then
  echo "      already in place, nothing to copy"
else
  mkdir -p "$DST" && cp -R "$SRC/." "$DST/" || { echo "      COPY FAILED"; exit 1; }
  echo "      done"
fi

echo; echo "[2/3] Find Python 3.8 or newer"
PY=""
for c in python3 python "py -3"; do
  if $c -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
    PY="$($c -c 'import sys; print(sys.executable)')"; break
  fi
done
if [ -z "$PY" ]; then
  echo "      Python 3.8+ not found. Install it (https://www.python.org/downloads/) and run again."; exit 1
fi
echo "      using $PY"
echo "$PY" > "$DST/python_path.txt"

echo; echo "[3/3] Test run: 3 funds from MoneyDJ category 47"
TEST="${TMPDIR:-/tmp}/$NAME-test"
if ! PYTHONIOENCODING=utf-8 "$PY" "$DST/scripts/fund_nav_high_report.py" --category 47 --limit 3 --no-cache --out "$TEST/report.html"; then
  echo "      TEST FAILED - check the internet connection, or whether moneydj.com is reachable."; exit 1
fi
echo; echo "Installed. Test report: $TEST/report.html"
echo "In Claude Code type  /$NAME  or paste a MoneyDJ iQuoteFundCatFund URL."
echo "Optional data check needs Node.js + Playwright, see README.md."
