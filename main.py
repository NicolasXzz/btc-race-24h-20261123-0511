#!/usr/bin/env python3
"""TrendDipBounce: a near-trend dip-catcher for cbBTC/USDC, 1-minute bars.

Strategy (C1): long only, one open position, full size.

Entry (flat only, decided on a bar close, filled at the next bar's open),
all of these must hold, with at least 90 bars of history:

  1. Uptrend: close > SMA(60) and SMA(20) > SMA(60), and the 60-bar
     return is at least +20 bps.
  2. Near the trend, never extended: (close / SMA(60) - 1) <= 25 bps.
  3. Dip: close is at least 20 bps below the highest high of the last
     10 bars.
  4. Bounce: close > close 3 bars ago.
  5. Volatility window: ATR(14) between 4 and 60 bps of price.
  6. At least 15 bars since the last exit (cooldown).

Exit (whole position, any one fires):

  1. Profit target: position value >= cost * 1.015 (+150 bps).
  2. Hard stop: position value <= cost * 0.99 (-100 bps).
  3. Trend break: close < SMA(60).
  4. Max hold: 240 bars since the entry was decided.
  5. Trailing stop: once value >= cost * 1.0015 (armed at +15 bps),
     exit if close <= peak close since entry * (1 - 100 bps).

The five exit checks live in Bot.should_exit(), evaluated in the
order listed above; it returns which exit fired (or None).
Every order carries max_slippage_bps = 100. Sizing is full cash on
every buy. Deterministic, standard library only: no network, no wall
clock, no randomness, no file reads. Indicators use float closes only;
all money comparisons use the exact integer values the harness reports
(position value at the latest close, position cost including fees).

Speaks agent-fun/bars-replay/v1 on stdin/stdout via the vendored shim.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

import makefun_bars

SYMBOL = "CBBTC"

# --- C1 parameters (bps unless noted) ---
SMA_FAST = 20
SMA_SLOW = 60
RET60_MIN_BPS = 20
TREND_CAP_BPS = 25
DIP_BPS = 20
BOUNCE_BARS = 3
HH_BARS = 10
ATR_SPAN = 14
ATR_MIN_BPS = 4
ATR_MAX_BPS = 60
TP_BPS = 150
TRAIL_BPS = 100
TRAIL_ARM_BPS = 15
STOP_BPS = 100
MAX_HOLD_BARS = 240
EXIT_SMA_SPAN = 60
MIN_HISTORY_BARS = 90
COOLDOWN_BARS = 15
MAX_SLIPPAGE_BPS = 100
MIN_NOTIONAL = 1000000  # quote units ($1)


class Bot:
    """Keeps bar history and position bookkeeping across batches."""

    def __init__(self):
        self.closes = []  # float closes in dollars (raw close / 1e5)
        self.highs = []
        self.lows = []
        self.close_pref = [0.0]  # prefix sums of closes
        self.tr_pref = [0.0]  # prefix sums of true ranges
        self.entry_i = None  # bar index the current entry was decided on
        self.peak = None  # highest close since entry (float dollars)
        self.last_exit_i = -10 ** 9  # bar index the last exit filled on
        self.prev_had = False
        self.pending_buy_seq = None  # seq of the batch a buy was sent on

    def _sma(self, span, i):
        if i + 1 < span:
            return None
        return (self.close_pref[i + 1] - self.close_pref[i + 1 - span]) / span

    def _atr(self, span, i):
        if i < span:
            return None
        return (self.tr_pref[i + 1] - self.tr_pref[i + 1 - span]) / span

    def should_exit(self, i, close, sma_slow, value, cost):
        """Exit decision, evaluated in the fixed order below.

        All money comparisons use the exact integers the harness
        reports (position value at the latest close, position cost
        including fees); the trailing check uses float closes. The
        caller must have updated self.peak for this bar first.
        Returns the exit reason, or None to stay in the position.
        """
        if value * 10000 >= cost * (10000 + TP_BPS):
            return "tp"
        if value * 10000 <= cost * (10000 - STOP_BPS):
            return "stop"
        if close < sma_slow:
            return "trend_break"
        if self.entry_i is not None and i - self.entry_i >= MAX_HOLD_BARS:
            return "max_hold"
        if value * 10000 >= cost * (10000 + TRAIL_ARM_BPS):
            if self.peak is not None and close <= self.peak * (1.0 - TRAIL_BPS / 10000.0):
                return "trailing"
        return None

    def on_batch(self, state, batch):
        i = state.seq
        bar = state.latest[SYMBOL]
        close = int(bar["c"]) / 1e5
        high = int(bar["h"]) / 1e5
        low = int(bar["l"]) / 1e5
        self.closes.append(close)
        self.highs.append(high)
        self.lows.append(low)
        self.close_pref.append(self.close_pref[-1] + close)
        prev_close = self.closes[i - 1] if i > 0 else close
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        self.tr_pref.append(self.tr_pref[-1] + tr)

        holding = state.positions.get(SYMBOL)
        had = holding is not None

        # Fold in fills that landed on this bar (the account the shim
        # applied already reflects them): a new position fixes the entry
        # bar and the starting peak; a vanished position fixes the exit.
        if had and not self.prev_had:
            self.entry_i = self.pending_buy_seq if self.pending_buy_seq is not None else i - 1
            self.peak = self.closes[self.entry_i]
        if not had and self.prev_had:
            self.last_exit_i = i
        if not had:
            # Any buy sent on an earlier batch did not fill.
            self.pending_buy_seq = None
            self.entry_i = None
            self.peak = None
        self.prev_had = had

        if state.warming_up:
            return None
        if i < MIN_HISTORY_BARS:
            return None

        sma_fast = self._sma(SMA_FAST, i)
        sma_slow = self._sma(SMA_SLOW, i)
        atr = self._atr(ATR_SPAN, i)
        if sma_fast is None or sma_slow is None or atr is None:
            return None

        if had:
            if self.peak is not None and close > self.peak:
                self.peak = close
            value = state.value(SYMBOL, holding.qty)
            cost = holding.cost
            if self.should_exit(i, close, sma_slow, value, cost) is not None:
                return self._sell(holding)
            return None

        # Flat: entry, all filters must hold.
        if i - self.last_exit_i < COOLDOWN_BARS:
            return None
        if not (close > sma_slow and sma_fast > sma_slow):
            return None
        if (close / sma_slow - 1.0) * 10000.0 > TREND_CAP_BPS:
            return None
        if (close / self.closes[i - 60] - 1.0) * 10000.0 < RET60_MIN_BPS:
            return None
        atr_bps = atr / close * 10000.0
        if not (ATR_MIN_BPS <= atr_bps <= ATR_MAX_BPS):
            return None
        hh = max(self.highs[i - HH_BARS + 1:i + 1])
        if (hh - close) / hh * 10000.0 < DIP_BPS:
            return None
        if close <= self.closes[i - BOUNCE_BARS]:
            return None
        notional = state.cash
        if notional < MIN_NOTIONAL:
            return None
        self.pending_buy_seq = i
        return [{"side": "buy", "symbol": SYMBOL,
                 "notional_quote_units": notional,
                 "max_slippage_bps": MAX_SLIPPAGE_BPS}]

    @staticmethod
    def _sell(holding):
        return [{"side": "sell", "symbol": SYMBOL, "qty": holding.qty,
                 "max_slippage_bps": MAX_SLIPPAGE_BPS}]


def main():
    bot = Bot()
    makefun_bars.run(bot.on_batch)


if __name__ == "__main__":
    main()
