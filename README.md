# Strategy repository

This repository contains a custom Freqtrade strategy `Strategy005ProRev16`.

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
levels that can be tuned via hyperparameters. Minimal ROI is intentionally disabled to
avoid conflicts with the dynamic ROI logic.

Testing and hyperoptimization are recommended before live deployment.
