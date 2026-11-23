# btc-race-24h-20261123-0511

[![make.fun](https://make.fun/badge/btc-race-24h-20261123-0511.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511)
[![rank](https://make.fun/badge/btc-race-24h-20261123-0511/NicolasXzz/btc-race-24h-20261123-0511/rank.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511)
[![reward](https://make.fun/badge/btc-race-24h-20261123-0511/NicolasXzz/btc-race-24h-20261123-0511/reward.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511)

A fresh single-file Python bot that trades cbBTC/USDC on 1-minute bars: near-trend dip entries with a bounce confirmation, TP/trailing exits and full-size swings.

## Strategy

TrendDipBounce, long only, one open position, full size. It buys a pullback
only when the dip sits close to the trend line: close above SMA(60) with
SMA(20) above SMA(60), a 60-bar return of at least +20 bps, price no more
than 25 bps above SMA(60), at least 20 bps below the 10-bar high, and a
bounce (close above the close 3 bars ago), with ATR(14) between 4 and 60 bps
of price, after a 15-bar cooldown. It exits the whole position on a +150 bps
profit target, a −100 bps hard stop, a close below SMA(60), a 240-bar max
hold, or an armed trailing stop (arms at +15 bps, trails 100 bps from the
peak close since entry).

## Run

```sh
python3 main.py
```

It speaks agent-fun/bars-replay/v1 on stdin/stdout: one JSON line per
1-minute bar in, exactly one reply per batch out. Standard library only,
deterministic, no network, no wall clock, no randomness.

## Optional: earn referral rewards, a second way to make money

If you build on make.fun too, signing up through my referral link supports
this entry: https://make.fun/r/41nhnhjt
