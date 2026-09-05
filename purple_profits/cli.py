from __future__ import annotations

import argparse, csv, json
from datetime import datetime
from pathlib import Path

from .core import Bar, Config, backtest, summary


def _bars(path: Path) -> list[Bar]:
    with path.open(newline="") as f:
        rows = csv.DictReader(f)
        required = {"timestamp", "open", "high", "low", "close"}
        if not rows.fieldnames or not required.issubset(rows.fieldnames):
            raise ValueError(f"CSV requires columns: {', '.join(sorted(required))}")
        result = []
        for row in rows:
            stamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError("timestamp must contain a UTC offset")
            result.append(Bar(stamp, row.get("ticker") or "UNKNOWN", *(float(row[x]) for x in ("open", "high", "low", "close"))))
    return result


def main() -> None:
    p = argparse.ArgumentParser(description="No-lookahead Purple Profits 10-minute-bar backtest")
    p.add_argument("csv", type=Path)
    p.add_argument("--trades-out", type=Path, default=Path("trades.csv"))
    p.add_argument("--summary-out", type=Path)
    p.add_argument("--shares", type=int, default=100)
    p.add_argument("--slippage-bps", type=float, default=0)
    p.add_argument("--commission-per-share", type=float, default=0)
    args = p.parse_args()
    c = Config(shares=args.shares, slippage_bps=args.slippage_bps, commission_per_share=args.commission_per_share)
    trades = backtest(_bars(args.csv), c)
    report = summary(trades, c)
    text = json.dumps(report, indent=2, default=str)
    print(text)
    if args.summary_out:
        args.summary_out.write_text(text + "\n")
    with args.trades_out.open("w", newline="") as f:
        out = csv.writer(f)
        out.writerow(["ticker", "side", "entry_time", "entry_price", "stop_at_entry", "target", "exit_time", "exit_price", "shares", "reason", "trade_gross_pnl"])
        for t in trades:
            for stamp, price, qty, reason in t.exits:
                out.writerow([t.ticker, t.side, t.entry_time.isoformat(), t.entry_price, t.initial_stop, t.target, stamp.isoformat(), price, qty, reason, t.pnl])


if __name__ == "__main__":
    main()
