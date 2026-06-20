#!/usr/bin/env python3
"""Hourly surge stock fetcher.

Data sources:
  1. yfinance EquityQuery  — top daily gainers in Japan (reliable)
  2. Yahoo Mobile Search   — SNS/news buzz for 株+急騰 (HTML scrape)

Saves to: data/yahoo_realtime/YYYYMMDD_HHMM.json + latest.json + CSV
Optional:  simulator.db (SQLite), Google Sheets
"""

import csv
import json
import os
import smtplib
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
from bs4 import BeautifulSoup

try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent.parent.parent / "investment_simulator" / ".env"
    if _env_path.exists():
        load_dotenv(dotenv_path=_env_path, override=False)
except ImportError:
    pass

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

DATA_DIR = _ROOT / "data" / "yahoo_realtime"
SIMULATOR_DB = _ROOT.parent / "investment_simulator" / "data" / "simulator.db"

_MOBILE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9",
}


# ---------------------------------------------------------------------------
# 1. Surge ranking via yfinance EquityQuery
# ---------------------------------------------------------------------------

def fetch_surge_ranking(top_n: int = 30) -> list[dict]:
    """Get top daily gainers in Japan using yfinance EquityQuery."""
    results = []
    try:
        from src.data import yahoo_client
        from src.core.screening.query_builder import build_query

        criteria = {"min_market_cap": 10_000_000_000}
        query = build_query(criteria, region="jp")

        quotes = yahoo_client.screen_stocks(
            query,
            size=250,
            max_results=250,
            sort_field="percentchange",
            sort_asc=False,
        )
        for q in quotes[:top_n]:
            # regularMarketChangePercent is already in % units (e.g. 23.22 = 23.22%)
            change = q.get("regularMarketChangePercent", 0)
            volume = q.get("regularMarketVolume") or q.get("averageDailyVolume3Month", 0)
            results.append({
                "source": "yfinance_eq",
                "symbol": q.get("symbol", ""),
                "name": q.get("shortName") or q.get("longName", ""),
                "price": q.get("regularMarketPrice", ""),
                "change_pct": round(float(change), 2) if change else "",
                "volume": volume,
            })
        print(f"  Surge ranking: {len(results)} stocks")
    except Exception as e:
        print(f"  Warning: surge ranking failed: {e}", file=sys.stderr)
    return results


# ---------------------------------------------------------------------------
# 2. Yahoo mobile search for SNS buzz
# ---------------------------------------------------------------------------

def fetch_realtime_buzz(query: str = "株 急騰") -> list[dict]:
    """Scrape Yahoo Search news headlines for stock surge buzz."""
    results = []
    try:
        import urllib.parse
        url = (
            "https://search.yahoo.co.jp/search"
            f"?p={urllib.parse.quote(query)}&ei=UTF-8&n=20"
        )
        hdrs = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ja-JP,ja;q=0.9",
        }
        resp = requests.get(url, headers=hdrs, timeout=15)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        seen: set[str] = set()

        for a in soup.select("h3 a, [class*='Title'] a, .sw-Card__title a"):
            text = a.get_text(strip=True)
            if text and 8 <= len(text) <= 80 and text not in seen:
                seen.add(text)
                results.append({"source": "yahoo_search", "headline": text})
            if len(results) >= 20:
                break

        print(f"  Yahoo buzz headlines: {len(results)} items")
    except Exception as e:
        print(f"  Warning: Yahoo buzz fetch failed: {e}", file=sys.stderr)
    return results


def fetch_general_buzz(top_n: int = 10) -> list[dict]:
    """Scrape Yahoo Realtime Search trending words (急上昇ワード, all topics).

    Unlike fetch_realtime_buzz (stock-only), this returns general SNS buzz
    across every topic, so it complements the stock-focused notification.
    """
    import re

    results: list[dict] = []
    try:
        url = "https://search.yahoo.co.jp/realtime"
        hdrs = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ja-JP,ja;q=0.9",
        }
        resp = requests.get(url, headers=hdrs, timeout=15)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        seen: set[str] = set()

        for a in soup.select("[class*='Trend'] a"):
            text = a.get_text(strip=True)
            # Strip the leading rank number (e.g. "1オジュウチョウサン" -> "オジュウチョウサン")
            text = re.sub(r"^\d+", "", text).strip()
            if text and 1 <= len(text) <= 40 and text not in seen:
                seen.add(text)
                results.append({"source": "yahoo_realtime", "headline": text})
            if len(results) >= top_n:
                break

        print(f"  Yahoo general buzz words: {len(results)} items")
    except Exception as e:
        print(f"  Warning: Yahoo general buzz fetch failed: {e}", file=sys.stderr)
    return results


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------

def save_files(surge: list[dict], buzz: list[dict], general_buzz: list[dict] | None = None) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")

    payload = {
        "timestamp": ts,
        "surge_ranking": surge,
        "buzz": buzz,
        "general_buzz": general_buzz or [],
    }
    for path in [DATA_DIR / f"{ts}.json", DATA_DIR / "latest.json"]:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    if surge:
        csv_path = DATA_DIR / f"{ts}_surge.csv"
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(surge[0].keys()))
            writer.writeheader()
            writer.writerows(surge)
        print(f"  Saved CSV: {csv_path.name}")

    print(f"  Saved JSON: {ts}.json + latest.json")


def save_sqlite(surge: list[dict]) -> None:
    if not SIMULATOR_DB.exists():
        return
    try:
        conn = sqlite3.connect(str(SIMULATOR_DB))
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS yahoo_surge_ranking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fetched_at TEXT, symbol TEXT, name TEXT,
                price TEXT, change_pct TEXT, volume INTEGER
            )
        """)
        ts = datetime.now().isoformat()
        for r in surge:
            cur.execute(
                "INSERT INTO yahoo_surge_ranking (fetched_at, symbol, name, price, change_pct, volume)"
                " VALUES (?,?,?,?,?,?)",
                (ts, r.get("symbol"), r.get("name"), r.get("price"),
                 r.get("change_pct"), r.get("volume")),
            )
        conn.commit()
        conn.close()
        print(f"  Saved {len(surge)} rows to simulator.db")
    except Exception as e:
        print(f"  Warning: SQLite save failed: {e}", file=sys.stderr)


def save_gsheets(surge: list[dict]) -> None:
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

        sheet = client.open("Investment Data").worksheet("Yahoo急騰ランキング")
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        rows = [
            [ts, r["symbol"], r["name"], r["price"], r["change_pct"], r.get("volume", "")]
            for r in surge
        ]
        sheet.append_rows(rows)
        print(f"  Google Sheets: appended {len(rows)} rows")
    except ImportError:
        pass
    except Exception as e:
        print(f"  Warning: Google Sheets failed: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Telegram notification
# ---------------------------------------------------------------------------

_JST = timezone(timedelta(hours=9))


def _is_trading_hours() -> bool:
    now = datetime.now(_JST)
    if now.weekday() >= 5:
        return False
    return 9 <= now.hour < 20


def send_telegram_alert(surge: list[dict], buzz: list[dict]) -> None:
    token = os.getenv("TELEGRAM_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    if not _is_trading_hours():
        return

    now = datetime.now(_JST)
    lines = [f"🔥 Yahooバズ投稿 TOP10 ({now.strftime('%H:%M')} JST)"]

    if buzz:
        for i, b in enumerate(buzz[:10], 1):
            lines.append(f"{i}. {b.get('headline', '')}")
    else:
        lines.append("（バズ投稿なし）")

    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": "\n".join(lines)},
            timeout=10,
        )
        print("  Telegram: notification sent")
    except Exception as e:
        print(f"  Warning: Telegram notification failed: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def send_email_alert(surge: list[dict]) -> None:
    email_from = os.getenv("EMAIL_FROM", "")
    email_pw = os.getenv("EMAIL_PASSWORD", "")
    email_to = os.getenv("EMAIL_TO", "")
    if not all([email_from, email_pw, email_to]):
        return

    now = datetime.now(_JST)
    subject = f"[Yahoo急騰] 本日のTOP5 ({now.strftime('%H:%M')} JST)"

    rows = ""
    for i, s in enumerate(surge[:5], 1):
        name = s.get("name") or s.get("symbol", "")
        symbol = s.get("symbol", "")
        pct = s.get("change_pct", "")
        price = s.get("price", "")
        rows += (
            f"<tr style='background:{'#0f3460' if i%2==0 else 'transparent'};'>"
            f"<td style='padding:8px;color:#a0a0b0;'>{i}</td>"
            f"<td style='padding:8px;font-weight:bold;'>{name}</td>"
            f"<td style='padding:8px;color:#a0a0b0;'>{symbol}</td>"
            f"<td style='padding:8px;font-size:16px;font-weight:bold;color:#4ade80;'>+{pct}%</td>"
            f"<td style='padding:8px;'>{price}</td>"
            f"</tr>"
        )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;background:#1a1a2e;color:#e0e0e0;padding:20px;">
  <div style="max-width:560px;margin:auto;background:#16213e;border-radius:12px;padding:24px;">
    <h2 style="color:#e94560;margin-top:0;">📈 Yahoo急騰 TOP5</h2>
    <p style="color:#a0a0b0;font-size:13px;">{now.strftime('%Y年%m月%d日 %H:%M JST')}</p>
    <table style="width:100%;border-collapse:collapse;margin:16px 0;">
      <tr style="background:#0f3460;">
        <th style="padding:8px;color:#a0a0b0;">順位</th>
        <th style="padding:8px;color:#a0a0b0;">銘柄名</th>
        <th style="padding:8px;color:#a0a0b0;">コード</th>
        <th style="padding:8px;color:#a0a0b0;">上昇率</th>
        <th style="padding:8px;color:#a0a0b0;">株価</th>
      </tr>
      {rows}
    </table>
  </div>
</body></html>"""

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = email_from
        msg["To"] = email_to
        msg.attach(MIMEText(html, "html", "utf-8"))
        with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
            smtp.starttls()
            smtp.login(email_from, email_pw)
            smtp.sendmail(email_from, email_to, msg.as_string())
        print(f"  Email: TOP5 alert sent to {email_to}")
    except Exception as e:
        print(f"  Warning: Email send failed: {e}", file=sys.stderr)


def main() -> int:
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] Surge fetch started")
    surge = fetch_surge_ranking()
    buzz = fetch_realtime_buzz()
    general_buzz = fetch_general_buzz()
    if surge or buzz or general_buzz:
        save_files(surge, buzz, general_buzz)
        save_sqlite(surge)
        save_gsheets(surge)
        # Telegram "Yahooバズ投稿 TOP10" uses general (all-topic) buzz so it is
        # not redundant with the stock-only "Yahoo SNSバズ 株関連" notification.
        send_telegram_alert(surge, general_buzz)
        # Email alert disabled per user request (2026-06-15). send_email_alert()
        # is kept for reference but no longer called.
    else:
        print("  No data fetched.")
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
