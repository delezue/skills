#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Research Harness² (arXiv:2610.14224) 雙層遞迴 Agent 駕馭與量化對帳實證引擎
Skill: harness2
"""

import os
import sys
import json
import argparse
import tempfile
from pathlib import Path

from harness2.cli import demo as h2_demo


def main():
    parser = argparse.ArgumentParser(description='Harness² Recursive Agent Harnessing Runner')
    parser.add_argument('--k', type=int, default=2, help='Task-level recursion budget k')
    parser.add_argument('--output', type=str, default='', help='Output directory for runs and demo.json')
    args = parser.parse_args()

    out_dir = Path(args.output) if args.output else Path(tempfile.mkdtemp(prefix='harness2_run_'))
    out_dir.mkdir(parents=True, exist_ok=True)

    sys.argv = ['harness2-demo', '--output', str(out_dir), '--k', str(args.k)]
    rc = h2_demo.main()
    demo_json = out_dir / 'demo.json'
    if demo_json.is_file():
        data = json.loads(demo_json.read_text(encoding='utf-8'))
        print("\n=== Harness² 雙層遞迴執行結果摘要 (demo.json) ===")
        print(json.dumps(data, indent=2, ensure_ascii=False))
    sys.exit(rc)


if __name__ == '__main__':
    main()
