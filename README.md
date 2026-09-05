# Purple Profits Backtest

This repository turns the supplied discretionary strategy description into a **repeatable, conservative 10-minute-bar backtest**. It is a research tool, not investment advice or evidence that the strategy will be profitable.

## What is made mechanical

The original rules use terms such as “strong,” “controlled,” and “near.” This implementation exposes them as configuration fields rather than silently treating subjective judgments as facts:

- a breakout must clear both the prior regular-session extreme and the same-day pre-market extreme;
- the impulse must contain `impulse_bars` directional, clean candles and clear the range by `breakout_buffer_bps`;
- a pullback is limited to `max_pullback_bars`, has bounded candle ranges/body size, and must preserve higher lows (long) or lower highs (short);
- the entry signal touches the 8 EMA and closes back on the trend side. It is filled at the **next bar's open**, never at the signal bar's close;
- the first target is the HOD/LOD **known before entry**, not a future day extreme; half the position exits there;
- the runner uses the previous completed bar's EMA as a trailing stop. If a bar touches both stop and target, the stop wins.

These choices deliberately avoid common hindsight biases. Slippage and fees are charged on every fill.

## Input data

Provide one CSV containing 10-minute OHLCV bars. `timestamp,open,high,low,close` are required; `ticker` and `volume` are optional. Timestamps must be ISO-8601 with an offset (UTC is recommended). The data must include pre-market bars from 04:00 through 09:30 New York time, otherwise an outside-day check cannot be made honestly.

```csv
timestamp,ticker,open,high,low,close,volume
2025-01-02T14:30:00+00:00,NVDA,138.0,138.8,137.7,138.6,125000
```

## Run

No third-party packages are required.

```bash
python -m purple_profits data/bars.csv --trades-out results/trades.csv --summary-out results/summary.json
# or after installing: purple-backtest data/bars.csv
```

Use `--help` to inspect every assumption. A basic cost-sensitive run is:

```bash
python -m purple_profits data/bars.csv --slippage-bps 2 --commission-per-share 0.005 \
  --shares 100 --trades-out results/trades.csv
```

## Interpreting the output

The CLI emits a JSON summary with trades, win rate, gross profit/loss, profit factor, net P&L, and maximum closed-trade drawdown. The trade CSV contains every entry/exit leg and its timestamp/reason. Validate out of sample by ticker and date, include delisted symbols, and do not optimize parameters on the same sample used to report results.

## Limitations

- 10-minute OHLC bars cannot reveal intrabar order. The engine resolves target/stop collisions pessimistically.
- A bar-based stop can gap beyond its level; this engine fills a gap at the opening price and otherwise at the stop.
- “Daily resistance/support” remains discretionary and is intentionally not invented as a hidden rule. The runner exits by EMA only.
- Corporate actions, borrow availability, halts, liquidity, option pricing, market impact, and taxes are outside this first implementation.

Run the automated checks with `python -m unittest discover -s tests -v`.
