#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lightpanda Headless Browser Python Bridge & CLI
Supports Windows (via WSL2 proxy) and Linux/macOS native execution.
"""

import os
import sys
import json
import shutil
import argparse
import subprocess
import urllib.request
import urllib.error

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def detect_lightpanda_command():
    """Detect whether lightpanda is available natively or via WSL."""
    # Check native lightpanda first
    native_path = shutil.which("lightpanda")
    if native_path:
        return [native_path]

    # Check Windows WSL
    if sys.platform == "win32":
        try:
            res = subprocess.run(
                ["wsl", "which", "lightpanda"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=5,
            )
            if res.returncode == 0 and res.stdout.strip():
                return ["wsl", res.stdout.strip()]
            
            # Check ~/.local/bin/lightpanda in WSL
            res2 = subprocess.run(
                ["wsl", "test", "-f", "$HOME/.local/bin/lightpanda"],
                capture_output=True,
                timeout=5,
            )
            if res2.returncode == 0:
                return ["wsl", "$HOME/.local/bin/lightpanda"]
        except Exception:
            pass

    return None


def get_version():
    """Get Lightpanda version."""
    base_cmd = detect_lightpanda_command()
    if not base_cmd:
        return None
    try:
        if base_cmd[0] == "wsl" and "$HOME" in base_cmd[1]:
            cmd = ["wsl", "bash", "-c", f"{base_cmd[1]} version"]
        else:
            cmd = base_cmd + ["version"]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=10)
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return None


def fetch(
    url: str,
    dump: str = "markdown",
    wait_ms: int = 1500,
    selector: str = None,
    timeout: int = 30,
) -> str:
    """
    Fetch a URL using Lightpanda and return the dumped content.
    dump options: 'markdown', 'html', 'structured_data', 'semantic_tree'
    """
    base_cmd = detect_lightpanda_command()
    if not base_cmd:
        raise RuntimeError("Lightpanda binary not found. Please install lightpanda in WSL or native environment.")

    args = ["fetch", url, "--dump", dump, "--wait-ms", str(wait_ms)]
    if selector:
        args.extend(["--dump-selector", selector])

    if base_cmd[0] == "wsl" and "$HOME" in base_cmd[1]:
        full_cli = f"{base_cmd[1]} " + " ".join(f'"{a}"' for a in args)
        cmd = ["wsl", "bash", "-c", full_cli]
    else:
        cmd = base_cmd + args

    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        errors="replace",
    )
    if res.returncode != 0:
        err_msg = res.stderr.strip() or f"Process exited with code {res.returncode}"
        raise RuntimeError(f"Lightpanda fetch failed: {err_msg}")

    return res.stdout


def fetch_markdown(url: str, wait_ms: int = 1500, selector: str = None) -> str:
    """Fetch URL and dump as clean Markdown."""
    return fetch(url, dump="markdown", wait_ms=wait_ms, selector=selector)


def fetch_html(url: str, wait_ms: int = 1500, selector: str = None) -> str:
    """Fetch URL and dump as rendered HTML."""
    return fetch(url, dump="html", wait_ms=wait_ms, selector=selector)


def fetch_structured_data(url: str, wait_ms: int = 1500) -> dict:
    """Fetch URL and parse structured data (JSON-LD, OpenGraph, Twitter card, meta)."""
    raw = fetch(url, dump="structured_data", wait_ms=wait_ms)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


def check_cdp_status(host: str = "127.0.0.1", port: int = 9222) -> dict:
    """Check if Lightpanda CDP daemon is active."""
    url = f"http://{host}:{port}/json/version"
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {"active": True, "data": data}
    except Exception as e:
        return {"active": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(
        description="Lightpanda Headless Browser CLI & Bridge"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # status
    subparsers.add_parser("status", help="Check Lightpanda installation & CDP server status")

    # fetch
    fetch_parser = subparsers.add_parser("fetch", help="Fetch URL and extract content")
    fetch_parser.add_argument("url", help="Target URL")
    fetch_parser.add_argument(
        "--dump",
        choices=["markdown", "html", "structured_data", "semantic_tree"],
        default="markdown",
        help="Dump format (default: markdown)",
    )
    fetch_parser.add_argument(
        "--wait-ms",
        type=int,
        default=1500,
        help="Time to wait after load in ms (default: 1500)",
    )
    fetch_parser.add_argument(
        "--selector",
        type=str,
        default=None,
        help="CSS selector to extract specific DOM element",
    )

    # serve
    serve_parser = subparsers.add_parser("serve", help="Run Lightpanda CDP WebSocket server")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Host interface (default: 0.0.0.0)")
    serve_parser.add_argument("--port", type=int, default=9222, help="Port (default: 9222)")

    # mcp
    mcp_parser = subparsers.add_parser("mcp", help="Run Lightpanda MCP server")
    mcp_parser.add_argument("--port", type=int, default=8080, help="MCP HTTP port (default: 8080)")

    args = parser.parse_args()

    if not args.command or args.command == "status":
        base_cmd = detect_lightpanda_command()
        version = get_version() if base_cmd else None
        cdp_stat = check_cdp_status()
        print("=== Lightpanda Environment Status ===")
        print(f"Command detected : {' '.join(base_cmd) if base_cmd else 'Not Found'}")
        print(f"Engine Version   : {version if version else 'Unavailable'}")
        print(f"CDP Server :9222 : {'Active (Connected)' if cdp_stat['active'] else 'Inactive (Not Running)'}")
        if cdp_stat["active"]:
            print(f"CDP Browser info : {cdp_stat['data']}")
        return

    if args.command == "fetch":
        try:
            output = fetch(
                args.url,
                dump=args.dump,
                wait_ms=args.wait_ms,
                selector=args.selector,
            )
            print(output)
        except Exception as e:
            sys.stderr.write(f"Error fetching {args.url}: {e}\n")
            sys.exit(1)

    elif args.command == "serve":
        base_cmd = detect_lightpanda_command()
        if not base_cmd:
            sys.stderr.write("Lightpanda binary not found.\n")
            sys.exit(1)
        serve_args = ["serve", "--host", args.host, "--port", str(args.port)]
        if base_cmd[0] == "wsl" and "$HOME" in base_cmd[1]:
            cmd = ["wsl", "bash", "-c", f"{base_cmd[1]} serve --host {args.host} --port {args.port}"]
        else:
            cmd = base_cmd + serve_args
        print(f"Starting Lightpanda CDP server on {args.host}:{args.port}...")
        subprocess.run(cmd)

    elif args.command == "mcp":
        base_cmd = detect_lightpanda_command()
        if not base_cmd:
            sys.stderr.write("Lightpanda binary not found.\n")
            sys.exit(1)
        if base_cmd[0] == "wsl" and "$HOME" in base_cmd[1]:
            cmd = ["wsl", "bash", "-c", f"{base_cmd[1]} mcp --port {args.port}"]
        else:
            cmd = base_cmd + ["mcp", "--port", str(args.port)]
        print(f"Starting Lightpanda MCP server on port {args.port}...")
        subprocess.run(cmd)


if __name__ == "__main__":
    main()
