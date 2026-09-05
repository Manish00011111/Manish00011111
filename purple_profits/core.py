from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, time
from statistics import median
from zoneinfo import ZoneInfo
from typing import Iterable

NY = ZoneInfo("America/New_York")
PREMARKET_START, REGULAR_START, REGULAR_END = time(4), time(9, 30), time(16)


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    ticker: str
    open: float
    high: float
    low: float
    close: float


@dataclass
class Config:
    ema_period: int = 8
    impulse_bars: int = 3
    breakout_buffer_bps: float = 5.0
    min_body_fraction: float = 0.45
    max_pullback_bars: int = 6
    max_pullback_range_multiple: float = 1.25
    max_pullback_body_fraction: float = 0.65
    shares: int = 100
    slippage_bps: float = 0.0
    commission_per_share: float = 0.0


@dataclass
class Trade:
    ticker: str
    side: str
    entry_time: datetime
    entry_price: float
    stop: float
    initial_stop: float
    target: float
    shares: int
    exits: list[tuple[datetime, float, int, str]]

    @property
    def pnl(self) -> float:
        direction = 1 if self.side == "long" else -1
        return sum((price - self.entry_price) * qty * direction for _, price, qty, _ in self.exits)


def is_regular(bar: Bar) -> bool:
    local = bar.timestamp.astimezone(NY)
    return REGULAR_START <= local.timetz().replace(tzinfo=None) < REGULAR_END


def is_premarket(bar: Bar) -> bool:
    local = bar.timestamp.astimezone(NY)
    clock = local.timetz().replace(tzinfo=None)
    return PREMARKET_START <= clock < REGULAR_START


def day_key(bar: Bar):
    return bar.timestamp.astimezone(NY).date()


def _ema(values: Iterable[float], period: int) -> list[float]:
    alpha = 2 / (period + 1)
    result: list[float] = []
    current = None
    for value in values:
        current = value if current is None else alpha * value + (1 - alpha) * current
        result.append(current)
    return result


def _fill(price: float, side: str, is_entry: bool, bps: float) -> float:
    # Costs worsen each fill: buys higher and sells lower.
    buy = (side == "long") == is_entry
    return price * (1 + (bps if buy else -bps) / 10_000)


def backtest(bars: list[Bar], config: Config = Config()) -> list[Trade]:
    """Backtest per ticker with only information available at each decision time."""
    by_ticker: dict[str, list[Bar]] = {}
    for bar in sorted(bars, key=lambda b: (b.ticker, b.timestamp)):
        if not (bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high):
            raise ValueError(f"Invalid OHLC bar at {bar.timestamp} ({bar.ticker})")
        by_ticker.setdefault(bar.ticker, []).append(bar)
    trades: list[Trade] = []
    for ticker_bars in by_ticker.values():
        trades.extend(_run_ticker(ticker_bars, config))
    return trades


def _run_ticker(bars: list[Bar], c: Config) -> list[Trade]:
    regular = [b for b in bars if is_regular(b)]
    regular_ema = dict(zip((b.timestamp for b in regular), _ema((b.close for b in regular), c.ema_period)))
    by_day: dict[object, list[Bar]] = {}
    for b in bars:
        by_day.setdefault(day_key(b), []).append(b)
    prior: dict[object, tuple[float, float]] = {}
    previous_regular: tuple[float, float] | None = None
    for day in sorted(by_day):
        prior[day] = previous_regular if previous_regular else (float("nan"), float("nan"))
        session = [b for b in by_day[day] if is_regular(b)]
        if session:
            previous_regular = (max(b.high for b in session), min(b.low for b in session))

    output: list[Trade] = []
    active: Trade | None = None
    pending: tuple[str, float, float, float] | None = None  # side, signal stop, target, signal EMA
    setup: dict[str, object] | None = None
    for i, b in enumerate(bars):
        if not is_regular(b):
            continue
        day = day_key(b)
        pm = [x for x in by_day[day] if is_premarket(x)]
        prev_high, prev_low = prior[day]
        if not pm or prev_high != prev_high:
            continue
        pm_high, pm_low = max(x.high for x in pm), min(x.low for x in pm)
        ema = regular_ema[b.timestamp]

        # A signal generated on the prior close is filled now, after open-based gap risk.
        if pending and active is None:
            side, stop, target, _ = pending
            entry = _fill(b.open, side, True, c.slippage_bps)
            if (side == "long" and entry > stop and target > entry) or (side == "short" and entry < stop and target < entry):
                active = Trade(b.ticker, side, b.timestamp, entry, stop, stop, target, c.shares, [])
            pending = None
        if active:
            _manage(active, b, ema, c)
            if sum(q for _, _, q, _ in active.exits) == active.shares:
                output.append(active)
                active = None
            continue

        history = [x for x in bars[:i + 1] if is_regular(x) and day_key(x) == day]
        if len(history) < c.impulse_bars + 2:
            continue
        buffer = c.breakout_buffer_bps / 10_000
        upper, lower = max(prev_high, pm_high) * (1 + buffer), min(prev_low, pm_low) * (1 - buffer)
        last = history[-c.impulse_bars:]
        long_impulse = all(x.close > x.open and (x.close - x.open) / (x.high - x.low or 1) >= c.min_body_fraction for x in last) and last[-1].close > upper
        short_impulse = all(x.close < x.open and (x.open - x.close) / (x.high - x.low or 1) >= c.min_body_fraction for x in last) and last[-1].close < lower
        if setup is None and (long_impulse or short_impulse):
            impulse_ranges = [x.high - x.low for x in last]
            setup = {"side": "long" if long_impulse else "short", "start": len(history), "ranges": impulse_ranges, "peak": last[-1].high if long_impulse else last[-1].low}
            continue
        if setup is None:
            continue
        side = str(setup["side"])
        pullback = history[int(setup["start"]):]
        if not pullback:
            continue
        if len(pullback) > c.max_pullback_bars:
            setup = None
            continue
        ranges = setup["ranges"]
        typical = median(ranges) * c.max_pullback_range_multiple
        clean = all((x.high - x.low) <= typical and abs(x.close - x.open) / (x.high - x.low or 1) <= c.max_pullback_body_fraction for x in pullback)
        if side == "long":
            setup["peak"] = max(float(setup["peak"]), b.high)
            structure = all(pullback[j].low >= pullback[j - 1].low for j in range(1, len(pullback)))
            touch = b.low <= ema and b.close > ema and b.close >= b.open
            stop, target = min(x.low for x in pullback), float(setup["peak"])
        else:
            setup["peak"] = min(float(setup["peak"]), b.low)
            structure = all(pullback[j].high <= pullback[j - 1].high for j in range(1, len(pullback)))
            touch = b.high >= ema and b.close < ema and b.close <= b.open
            stop, target = max(x.high for x in pullback), float(setup["peak"])
        if not clean or not structure:
            setup = None
        elif touch and ((side == "long" and target > b.close and stop < b.close) or (side == "short" and target < b.close and stop > b.close)):
            pending = (side, stop, target, ema)
            setup = None
    if active:  # End-of-data liquidation is explicit rather than assuming an unknown future exit.
        last = [b for b in bars if is_regular(b)][-1]
        active.exits.append((last.timestamp, _fill(last.close, active.side, False, c.slippage_bps), active.shares - sum(q for _, _, q, _ in active.exits), "end_of_data"))
        output.append(active)
    return output


def _manage(t: Trade, b: Bar, ema: float, c: Config) -> None:
    remaining = t.shares - sum(q for _, _, q, _ in t.exits)
    if not remaining:
        return
    # Current bar may hit the trailing stop and target; worst-case stop has priority.
    stopped = b.low <= t.stop if t.side == "long" else b.high >= t.stop
    target_hit = b.high >= t.target if t.side == "long" else b.low <= t.target
    if stopped:
        raw = min(b.open, t.stop) if t.side == "long" else max(b.open, t.stop)
        t.exits.append((b.timestamp, _fill(raw, t.side, False, c.slippage_bps), remaining, "stop_or_trail"))
        return
    if target_hit and remaining == t.shares:
        qty = t.shares // 2
        t.exits.append((b.timestamp, _fill(t.target, t.side, False, c.slippage_bps), qty, "prior_hod_lod"))
        remaining -= qty
    # EMA is observed at this bar's close, so it protects the next bar—not this one.
    if remaining:
        t.stop = max(t.stop, ema) if t.side == "long" else min(t.stop, ema)


def summary(trades: list[Trade], c: Config) -> dict:
    net = [t.pnl - c.commission_per_share * (t.shares + sum(q for _, _, q, _ in t.exits)) for t in trades]
    gross_profit = sum(x for x in net if x > 0)
    gross_loss = -sum(x for x in net if x < 0)
    equity = peak = drawdown = 0.0
    for value in net:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {"config": asdict(c), "trades": len(trades), "wins": sum(x > 0 for x in net), "win_rate": sum(x > 0 for x in net) / len(net) if net else 0, "gross_profit": gross_profit, "gross_loss": gross_loss, "profit_factor": gross_profit / gross_loss if gross_loss else None, "net_pnl": sum(net), "max_closed_trade_drawdown": drawdown}
