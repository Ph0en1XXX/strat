# Strategy repository

This repository contains a custom Freqtrade strategy `PhoeniX_V1` with an
example configuration ready for testing.

## Notes

- To reduce slippage on fast moves, you may enable on-exchange stoploss in your
  `config.json` when the exchange supports it:
  ```json
  "order_types": {
      "stoploss_on_exchange": true,
      "stoploss_on_exchange_limit_ratio": 0.995
  }
  ```
  Bybit does not support this feature, so it is disabled in the provided config.
- The custom stoploss cooperates with Freqtrade's trailing stop. You can enable
  `trailing_stop` in the config (enabled by default here with a 0.4% offset and
  0.1% positive offset). The strategy returns `None` when the trailing stop is
  active so both mechanisms cooperate.
- The strategy will close any trade after 12 hours via a timeout in
  `custom_exit`, ensuring positions don't linger indefinitely.
- Ensure TA-Lib is installed on your system, or use pandas-ta as an alternative for indicator calculations.
- Run `freqtrade analysis-reports lookahead-analysis` to verify that informative
 data does not introduce lookahead bias.

This strategy relies on an ATR-driven ROI target (`custom_roi`) and stepped
stop-loss levels that can be tuned via hyperparameters. `minimal_roi` is set to
`{}` to avoid conflicts with the dynamic ROI logic.  The ATR window now defaults
to 50 candles for better smoothing during high-volatility events.

Dynamic ROI now scales with recent volatility: pairs above 6% ATR aim for a
higher target while calm markets get a smaller multiplier.  The slope filter for
EMA-200 now uses `ema200_lrs` with a tunable threshold (default `0.0001`) to
avoid trades in flat trends.
The ROI multiplier itself is now a hyperopt parameter so you can adapt it to
different market conditions.

Recent updates tighten the base stoploss to `-6%`, lower the DCA gap for calm markets
and use more aggressive BTC-drop exits. The BTC-protection logic now adapts to
current volatility and gracefully disables itself when the `BTC.D` pair is not
available. A correlation filter avoids trading pairs that move almost identically
to BTC and will also trigger an exit if correlation spikes during a trade.
`max_entry_position_adjustment` is increased to 3 and the strategy can
scale out 33% of a position once profit exceeds 8%. `max_open_trades` defaults to
**6** and the example config limits overall exposure to 40% of the account balance. The LowProfitPairs protection is enabled by default. If your Freqtrade installation lacks the `PairsNotProfitable` plugin, remove that entry from the strategy to avoid load errors.

Testing and hyperoptimization are recommended before live deployment.

The strategy requires about 250 startup candles to calculate EMA‑200 and other
rolling indicators.  Set `startup_candle_count` accordingly in the strategy or
your configuration.

Hyperoptimization is supported via the `generate_buy_space` and
`generate_sell_space` functions.  Key thresholds such as ADX, ATR‑Z and the
EMA‑slope can now be tuned automatically.  Run hyperopt with `--spaces buy sell`
to search these parameters.

### BTC Dominance filter
The strategy can optionally use a BTC.D pair to filter entries and exits.
Bybit does not provide this market, so the filter is disabled by default.
If your exchange offers BTC.D or a similar dominance index, set
`use_btcd_filter = True` in the strategy to enable it.

## Usage

1. Copy `config.json` and update your API keys and Telegram credentials.
2. Place `PhoeniX_V1.py` in your `user_data/strategies` folder.
3. Run backtesting with `freqtrade backtesting -c config.json -s PhoeniX_V1`.
   The configuration leaves the whitelist empty and relies on the
   `VolumePairList` plugin to select the top 20 pairs by quote volume on
   your exchange.  The `min_value` threshold is set to `100000` so that
   enough markets qualify even on quieter days.  Adjust this value if you
   need more or fewer pairs.  This dynamic list lets the bot trade any
   high-liquidity market without manual updates.

4. Review the results and adjust parameters as needed.

If the log prints a message like `Throttling with '_process_running()'`, the bot
is pausing between cycles because of the `process_throttle_secs` setting in the
configuration (default is `5`).  Reduce this value if you want the strategy to
check for new signals more frequently, at the cost of slightly higher CPU
usage.
