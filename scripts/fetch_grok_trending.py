#!/usr/bin/env python3
"""Daily Grok API trending stock screener for Japan market."""

import csv
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

DATA_DIR = _ROOT / "data" / "grok_trending"
SIMULATOR_DB = _ROOT.parent / "investment_simulator" / "data" / "simulator.db"


def run_trending_screen(region: str = "jp", top_n: int = 20) -> list[dict]:
    """Run TrendingScreener via Grok API."""
    try:
        from src.data import yahoo_client
        from src.data import grok_client as gc

        if not gc.is_available():
            print("Error: XAI_API_KEY not set.", file=sys.stderr)
            return []

        from src.core.screening.trending_screener import TrendingScreener
        screener = TrendingScreener(yahoo_client, gc)
        results, _ctx = screener.screen(region=region, top_n=top_n)
        print(f"  Trending screener: {len(results)} stocks")
        return results
    except Exception as e:
        print(f"  Error: {e}", file=sys.stderr)
        return []


def save_files(results: list[dict], region: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d")

    payload = {"date": ts, "region": region, "results": results}
    for path in [DATA_DIR / f"{ts}_{region}.json", DATA_DIR / "latest.json"]:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    if results:
        csv_path = DATA_DIR / f"{ts}_{region}.csv"
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            writer.writeheader()
            writer.writerows(results)
        print(f"  Saved CSV: {csv_path.name}")

    print(f"  Saved JSON: {ts}_{region}.json + latest.json")


def save_sqlite(results: list[dict], region: str) -> None:
    if not SIMULATOR_DB.exists():
        return
    try:
        conn = sqlite3.connect(str(SIMULATOR_DB))
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS grok_trending (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fetched_at TEXT,
                region TEXT,
                symbol TEXT,
                name TEXT,
                reason TEXT,
                per REAL,
                pbr REAL,
                score REAL
            )
        """)
        ts = datetime.now().isoformat()
        for r in results:
            cur.execute("""
                INSERT INTO grok_trending (fetched_at, region, symbol, name, reason, per, pbr, score)
                VALUES (?,?,?,?,?,?,?,?)
            """, (
                ts, region,
                r.get("symbol"), r.get("name"), r.get("reason"),
                r.get("per"), r.get("pbr"), r.get("value_score"),
            ))
        conn.commit()
        conn.close()
        print(f"  Saved {len(results)} rows to simulator.db")
    except Exception as e:
        print(f"  Warning: SQLite save failed: {e}", file=sys.stderr)


def save_gsheets(results: list[dict], region: str) -> None:
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds_file = _ROOT.parent / "investment_screening_package" / "credentials.json"
        if not creds_file.exists():
            return

        scopes = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(str(creds_file), scopes=scopes)
        client = gspread.authorize(creds)

        sheet = client.open("Investment Data").worksheet("Grokトレンド銘柄")
        ts = datetime.now().strftime("%Y-%m-%d")
        rows = [
            [ts, region, r.get("symbol"), r.get("name"), r.get("reason"), r.get("value_score")]
            for r in results
        ]
        sheet.append_rows(rows)
        print(f"  Google Sheets: appended {len(rows)} rows")
    except ImportError:
        pass
    except Exception as e:
        print(f"  Warning: Google Sheets failed: {e}", file=sys.stderr)


def main() -> int:
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] Daily Grok trending screener started")
    region = "jp"
    results = run_trending_screen(region=region, top_n=20)
    if results:
        save_files(results, region)
        save_sqlite(results, region)
        save_gsheets(results, region)
    else:
        print("  No results.")
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
