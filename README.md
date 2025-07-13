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
- Run `freqtrade analysis-reports lookahead-analysis` to verify that informative
 data does not introduce lookahead bias.

This strategy relies on an ATR-driven ROI target (`custom_roi`) and stepped
stop-loss levels that can be tuned via hyperparameters. `minimal_roi` is set to
`{}` to avoid conflicts with the dynamic ROI logic.

Recent changes tighten the base stoploss to `-6%`, lower the DCA gap for calm markets
and use more aggressive BTC-drop exits. `max_entry_position_adjustment` is increased
to 3 for flexibility.

Testing and hyperoptimization are recommended before live deployment.

### BTC Dominance filter
The strategy can optionally use a BTC.D pair to filter entries and exits.
Bybit does not provide this market, so the filter is disabled by default.
If your exchange offers BTC.D or a similar dominance index, set
`use_btcd_filter = True` in the strategy to enable it.

## Usage

1. Copy `config.json` and update your API keys and Telegram credentials.
2. Place `PhoeniX_V1.py` in your `user_data/strategies` folder.
3. Run backtesting with `freqtrade backtesting -c config.json -s PhoeniX_V1`.
   The sample configuration trades a small whitelist of six major pairs
   (BTC/USDT, ETH/USDT, XRP/USDT, ADA/USDT, SOL/USDT and DOGE/USDT).

4. Review the results and adjust parameters as needed.
