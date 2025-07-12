# -*- coding: utf-8 -*-
"""
Strategy005Pro – rev‑16 (dominance & stepped‑SL, adaptive ROI)
============================================================

Модификации по сравнению с rev‑15:
1. **EMA‑200 slope** теперь рассчитывается в относительных процентах (`pct_change`) — это делает фильтр более масштаб‑инвариантным.
2. **atr_ema_std** заменён на реальное стандартное отклонение, что повышает точность z‑оценки.
3. Добавлен параметр **max_open_trades = 8** для ограничения совокупного риска.
4. В фильтре BTC‑dominance вынесена переменная `btcd_lookback` (по умолчанию 24 часа), что упрощает быструю подстройку.
5. Произведён косметический рефакторинг (переименование `ema200_slope20` → `ema200_slope20_pct`).
6. Скрипт совместим с Freqtrade ≥ 2025.4.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import talib.abstract as ta
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, stoploss_from_open
from freqtrade.strategy.hyper import IntParameter, DecimalParameter


class Strategy005ProRev16(IStrategy):
    """Trend‑following стратегия 2025‑26 с BTC‑dominance фильтром, stepped‑SL и DCA‑поддержкой."""

    # ---- Общие настройки ----------------------------------------------
    timeframe = "15m"
    informative_timeframe = "1h"
    high_tf = "4h"
    btc_fast_tf = "15m"

    max_open_trades = 8  # новое ограничение совокупных позиций

    # BTC dominance
    use_btcd_filter: bool = True  # можно выключить, если нет фида
    btcd_dom_threshold: float = 2.0  # %
    btcd_lookback: int = 24  # кол-во свечей informative_timeframe для расчёта изменения доминанса

    can_short = False
    use_custom_stoploss = True
    position_adjustment_enable = True
    use_exit_signal = True
    ignore_roi_if_exit_signal = True

    max_entry_position_adjustment = 2

    # ROI‑grid
    minimal_roi = {
        "0": 0.10,
        "60": 0.06,
        "120": 0.04,
        "480": 0
    }

    stoploss = -0.09

    trailing_stop = False  # конфликтует с custom_stoploss – оставляем False

    # ---- Гипер‑параметры ----------------------------------------------
    buy_min_atr_z = DecimalParameter(1.0, 3.5, default=1.7, space="buy", optimize=True)
    buy_adx_min = IntParameter(22, 38, default=27, space="buy", optimize=True)
    buy_vol_rel_min = DecimalParameter(1.2, 2.0, default=1.5, space="buy", optimize=True)

    atr_window = IntParameter(25, 60, default=28, space="buy", optimize=True)
    dca_gap_pct = DecimalParameter(0.6, 1.0, default=0.8, space="buy", optimize=True)

    max_trade_minutes = IntParameter(240, 720, default=420, space="sell", optimize=True)

    flat_adx_max = IntParameter(12, 18, default=15, space="sell", optimize=False)

    # -------------------------------------------------------------------
    def protections(self):
        return [
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 48,
                "trade_limit": 20,
                "stop_duration_candles": 12,
                "max_allowed_drawdown": 0.03,
            },
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 24,
                "trade_limit": 3,
                "stop_duration_candles": 6,
                "only_per_pair": False,
            },
            {
                "method": "CooldownPeriod",
                "stop_duration_candles": 2,
            },
        ]

    # -------------------------------------------------------------------
    def informative_pairs(self):
        wl = self.dp.current_whitelist()
        pairs = [(pair, self.informative_timeframe) for pair in wl]
        pairs += [(pair, self.high_tf) for pair in wl]
        pairs += [
            ("BTC/USDT", self.informative_timeframe),
            ("BTC/USDT", self.btc_fast_tf),
            ("BTC/USDT", self.high_tf),
        ]
        if self.use_btcd_filter:
            pairs.append(("BTC.D", self.informative_timeframe))
        return pairs

    # ---- Индикаторы ----------------------------------------------------
    def populate_indicators(self, df: DataFrame, metadata: dict) -> DataFrame:
        df["ema_200"] = ta.EMA(df, timeperiod=200)
        df["sma_40"] = ta.SMA(df, timeperiod=40)
        df["adx"] = ta.ADX(df)

        stoch = ta.STOCH(df)
        df["slowk"], df["slowd"] = stoch["slowk"], stoch["slowd"]

        # ATR‑волатильность
        atr_val = ta.ATR(df, timeperiod=14)
        df["atr_pct"] = atr_val / df["close"] * 100
        win = self.atr_window.value
        df["atr_ema"] = ta.EMA(df["atr_pct"], timeperiod=win)
        df["atr_ema_std"] = df["atr_pct"].rolling(win).std(ddof=0)
        df["atr_z"] = (df["atr_pct"] - df["atr_ema"]) / (df["atr_ema_std"] + 1e-9)

        # EMA‑200 относительный наклон (20 баров)
        df["ema200_slope20_pct"] = df["ema_200"].pct_change(20)

        # Quote‑volume
        if "quoteVolume" not in df.columns:
            if "volume" in df.columns:
                df["quoteVolume"] = df["volume"].replace(0, np.nan) * df["close"]
            elif "baseVolume" in df.columns:
                df["quoteVolume"] = df["baseVolume"].replace(0, np.nan) * df["close"]
            else:
                df["quoteVolume"] = np.nan
        df["vol_ma"] = df["quoteVolume"].rolling(96, min_periods=30).mean()

        return df

    # ---- Entry ---------------------------------------------------------
    def _btcd_change_ok(self) -> bool:
        if not self.use_btcd_filter:
            return True
        df_btcd = self.dp.get_pair_dataframe(pair="BTC.D", timeframe=self.informative_timeframe)
        if df_btcd is None or len(df_btcd) < self.btcd_lookback or df_btcd["close"].isna().all():
            return False
        change = (df_btcd["close"].iloc[-1] / df_btcd["close"].iloc[-self.btcd_lookback] - 1) * 100
        return change <= self.btcd_dom_threshold

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        if not self._btcd_change_ok():
            return df
        pair = metadata["pair"]
        df_htf = self.dp.get_pair_dataframe(pair=pair, timeframe=self.high_tf)
        if df_htf is None or len(df_htf) < 200:
            return df
        if "ema_200" not in df_htf.columns:
            df_htf["ema_200"] = ta.EMA(df_htf, timeperiod=200)
        up_trend = df_htf["close"].iloc[-1] > df_htf["ema_200"].iloc[-1]

        slope_cond = df["ema200_slope20_pct"] > 0.0005  # ≥ 0.05 %

        df.loc[
            (
                up_trend &
                slope_cond &
                (df["close"] > df["ema_200"]) &
                (df["close"] < df["sma_40"]) &
                (df["adx"] > self.buy_adx_min.value) &
                (df["slowk"] > df["slowd"]) &
                (df["slowk"].shift() <= df["slowd"].shift()) &
                (df["atr_z"] > self.buy_min_atr_z.value) &
                (df["quoteVolume"] > df["vol_ma"] * self.buy_vol_rel_min.value)
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "trend_pullback")
        return df

    # ---- Exit ----------------------------------------------------------
    def _btcd_exit(self) -> bool:
        if not self.use_btcd_filter:
            return False
        df_btcd = self.dp.get_pair_dataframe(pair="BTC.D", timeframe=self.informative_timeframe)
        if df_btcd is None or len(df_btcd) < self.btcd_lookback or df_btcd["close"].isna().all():
            return True
        change = (df_btcd["close"].iloc[-1] / df_btcd["close"].iloc[-self.btcd_lookback] - 1) * 100
        return change > self.btcd_dom_threshold

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        pair = metadata["pair"]
        df_htf = self.dp.get_pair_dataframe(pair=pair, timeframe=self.high_tf)
        global_bear = False
        if df_htf is not None and len(df_htf) > 200:
            if "ema_200" not in df_htf.columns:
                df_htf["ema_200"] = ta.EMA(df_htf, timeperiod=200)
            global_bear = (df_htf["close"].iloc[-2:] < df_htf["ema_200"].iloc[-2:]).all()

        low_adx = df["adx"].rolling(6).max() < self.flat_adx_max.value

        btcd_exit = self._btcd_exit()

        df.loc[
            (
                global_bear |
                btcd_exit |
                (df["slowk"] < df["slowd"]) |
                (df["close"] < df["ema_200"]) |
                low_adx
            ),
            "exit_long",
        ] = 1
        return df

    # ---- DCA -----------------------------------------------------------
    def _atr_pct_for_pair(self, pair: str) -> float | None:
        cache_key = f"atr_pct_{pair}"
        now = datetime.utcnow()
        cached = getattr(self, "_cache", {})
        if cache_key in cached:
            val, ts = cached[cache_key]
            if now - ts < timedelta(minutes=5):
                return val
        self._cache = {k: v for k, v in cached.items() if now - v[1] < timedelta(minutes=5)}
        df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
        if df is not None and "atr_pct" in df.columns:
            val = float(df["atr_pct"].iloc[-1])
            self._cache[cache_key] = (val, now)
            return val
        return None

    def adjust_trade_position(
        self,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        min_stake: float | None,
        max_stake: float,
        current_entry_rate: float,
        current_exit_rate: float,
        current_entry_profit: float,
        current_exit_profit: float,
        **kwargs,
    ):
        atr_pct = self._atr_pct_for_pair(trade.pair) or 3.0
        max_adj_allowed = 1 if atr_pct > 8 else self.max_entry_position_adjustment
        if trade.has_open_orders or trade.nr_of_position_adjustments >= max_adj_allowed:
            return None

        gap = max(atr_pct * self.dca_gap_pct.value / 100, 0.04)
        level_idx = trade.nr_of_position_adjustments
        target_price = trade.entry_price * (1 - gap * (level_idx + 1))

        if current_rate <= target_price:
            remaining = max_stake - trade.stake_amount
            if remaining <= 0:
                return None
            add_factor = 1.15 ** level_idx
            additional_stake = min(trade.stake_amount * add_factor, remaining)
            if min_stake and additional_stake < min_stake:
                return None
            return additional_stake, f"dca_{int(gap * 100)}%"
        return None

    # ---- Stop‑loss -----------------------------------------------------
    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        after_fill: bool = False,
        **kwargs,
    ):
        base_sl = -0.04 if trade.nr_of_position_adjustments >= 1 else -0.09
        if after_fill:
            return base_sl

        if current_profit > 0.12:
            return stoploss_from_open(0.10, current_profit, trade.is_short, trade.leverage)
        if current_profit > 0.07:
            return stoploss_from_open(0.05, current_profit, trade.is_short, trade.leverage)
        if current_profit > 0.04:
            return stoploss_from_open(0.03, current_profit, trade.is_short, trade.leverage)
        if current_profit > 0.02:
            return stoploss_from_open(0.015, current_profit, trade.is_short, trade.leverage)
        if current_profit > 0.01:
            return stoploss_from_open(0.0, current_profit, trade.is_short, trade.leverage)
        return base_sl

    # ---- Emergency exit ------------------------------------------------
    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ):
        btc_hour = self.dp.get_pair_dataframe(pair="BTC/USDT", timeframe=self.informative_timeframe)
        btc_fast = self.dp.get_pair_dataframe(pair="BTC/USDT", timeframe=self.btc_fast_tf)
        if btc_hour is not None and len(btc_hour) > 4 and btc_fast is not None and len(btc_fast) > 3:
            if "ema_200" not in btc_hour.columns:
                btc_hour["ema_200"] = ta.EMA(btc_hour, timeperiod=200)
            now_p, prev3h_p = btc_hour["close"].iloc[-1], btc_hour["close"].iloc[-4]
            prev30m_p = btc_fast["close"].iloc[-3]
            drop3h = now_p / prev3h_p - 1
            drop30m = now_p / prev30m_p - 1
            vol_spike = btc_fast["volume"].iloc[-1] > btc_fast["volume"].rolling(8).mean().iloc[-1] * 3
            if (now_p < btc_hour["ema_200"].iloc[-1]) or (drop3h < -0.07) or (drop30m < -0.02 and vol_spike):
                return "btc_protect"

        lifespan = (current_time - trade.open_date_utc).total_seconds() / 60
        if current_profit < 0.02 and lifespan > self.max_trade_minutes.value:
            return "timeout"

        df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
        if df is not None and len(df) > max(6, self.atr_window.value):
            if df["atr_z"].iloc[-6:].lt(0).all():
                return "atr_compression"
        return None
