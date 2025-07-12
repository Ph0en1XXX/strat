# Strategy repository

This repository contains a custom Freqtrade strategy `Strategy005ProRev16` with
an example configuration ready for testing.

## Notes

- To reduce slippage on fast moves, enable on-exchange stoploss in your `config.json`:
  ```json
  "order_types": {
      "stoploss_on_exchange": true,
      "stoploss_on_exchange_interval": 60
  }
  ```
- Run `freqtrade analysis-reports lookahead-analysis` to verify that informative
  data does not introduce lookahead bias.

This strategy relies on an ATR-driven ROI target (`custom_roi`) and stepped stop-loss
levels that can be tuned via hyperparameters. `minimal_roi` is set to `{}` to avoid
conflicts with the dynamic ROI logic.

Recent changes tighten the base stoploss to `-6%`, lower the DCA gap for calm markets
and use more aggressive BTC-drop exits. `max_entry_position_adjustment` is increased
to 3 for flexibility.

Testing and hyperoptimization are recommended before live deployment.

## Usage

1. Copy `config.json` and update your API keys and Telegram credentials.
2. Place `PhoeniX-V1.py` in your `user_data/strategies` folder.
3. Run backtesting with `freqtrade backtesting -c config.json -s Strategy005ProRev16`.
4. Review the results and adjust parameters as needed.
