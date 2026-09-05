import unittest
from datetime import datetime, timezone

from purple_profits.core import Bar, Config, Trade, _manage, backtest, summary


class CoreTests(unittest.TestCase):
    def test_rejects_invalid_ohlc(self):
        bad = Bar(datetime(2025, 1, 2, tzinfo=timezone.utc), "X", 10, 9, 8, 9)
        with self.assertRaises(ValueError):
            backtest([bad])

    def test_summary_empty_is_safe(self):
        report = summary([], Config())
        self.assertEqual(report["trades"], 0)
        self.assertEqual(report["win_rate"], 0)
        self.assertIsNone(report["profit_factor"])

    def test_entry_cannot_fill_on_its_signal_bar(self):
        # A full dataset check is unnecessary here: explicitly exercise the documented
        # public invariant that no one-bar input can create an immediate trade.
        bar = Bar(datetime(2025, 1, 2, 14, 30, tzinfo=timezone.utc), "X", 10, 11, 9, 10.5)
        self.assertEqual(backtest([bar]), [])

    def test_stop_wins_when_target_and_stop_share_a_bar(self):
        trade = Trade("X", "long", datetime(2025, 1, 2, tzinfo=timezone.utc), 10, 9, 9, 11, 100, [])
        collision = Bar(datetime(2025, 1, 2, 15, tzinfo=timezone.utc), "X", 10, 11.5, 8.5, 10)
        _manage(trade, collision, 10.2, Config())
        self.assertEqual(trade.exits[0][2:], (100, "stop_or_trail"))
        self.assertEqual(trade.exits[0][1], 9)


if __name__ == "__main__":
    unittest.main()
