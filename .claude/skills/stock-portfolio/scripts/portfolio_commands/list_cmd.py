"""Portfolio command: list -- Display raw CSV contents."""

import glob
import json
import os

from portfolio_commands import (
    HAS_PORTFOLIO_FORMATTER,
    HAS_PORTFOLIO_MANAGER,
    _fallback_load_csv,
    _print_no_portfolio_message,
    format_position_list,
    load_portfolio,
)


def _get_last_trade_dates(csv_path: str) -> dict:
    """Scan trade history and return the last trade datetime per symbol."""
    root = os.path.normpath(
        os.path.join(os.path.dirname(os.path.normpath(csv_path)), "..", "..", "..", "..")
    )
    trade_dir = os.path.join(root, "data", "history", "trade")
    if not os.path.isdir(trade_dir):
        return {}

    last_ts: dict = {}
    for filepath in glob.glob(os.path.join(trade_dir, "*.json")):
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
            symbol = data.get("symbol")
            ts = data.get("timestamp") or data.get("_saved_at") or data.get("date")
            if symbol and ts:
                if symbol not in last_ts or ts > last_ts[symbol]:
                    last_ts[symbol] = ts
        except Exception:
            pass

    # Format: "YYYY-MM-DD HH:MM"
    result = {}
    for symbol, ts in last_ts.items():
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(ts)
            result[symbol] = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            result[symbol] = ts[:16] if len(ts) >= 16 else ts
    return result


def cmd_list(csv_path: str) -> None:
    """Display raw CSV contents."""
    if HAS_PORTFOLIO_MANAGER:
        holdings = load_portfolio(csv_path)
    else:
        holdings = _fallback_load_csv(csv_path)

    if not holdings:
        _print_no_portfolio_message(csv_path)
        return

    last_trade_dates = _get_last_trade_dates(csv_path)
    for h in holdings:
        h["last_trade_date"] = last_trade_dates.get(h.get("symbol", ""), "-")

    if HAS_PORTFOLIO_FORMATTER:
        print(format_position_list(holdings))
        return

    # Fallback: print as markdown table
    print("## ポートフォリオ一覧\n")
    print("| 銘柄 | 保有数 | 取得単価 | 通貨 | 購入日 | 最終売買日 | メモ |")
    print("|:-----|------:|--------:|:-----|:-------|:----------|:-----|")
    for h in holdings:
        print(
            f"| {h['symbol']} | {h['shares']} | {h['cost_price']:.2f} "
            f"| {h.get('cost_currency', '-')} | {h.get('purchase_date', '-')} "
            f"| {h.get('last_trade_date', '-')} | {h.get('memo', '')} |"
        )
    print()
