# -*- coding: utf-8 -*-
"""
PhoeniX V1 – adaptive ROI with dominance filter
===============================================

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
from freqtrade.strategy import IStrategy, stoploss_from_open, merge_informative_pair
from freqtrade.strategy.hyper import IntParameter, DecimalParameter


class PhoenixV1(IStrategy):
    """Trend‑following стратегия 2025‑26 с BTC‑dominance фильтром, stepped‑SL и DCA‑поддержкой."""

    # ---- Общие настройки ----------------------------------------------
    timeframe = "15m"
    informative_timeframe = "1h"
    high_tf = "4h"
    btc_fast_tf = "15m"

    max_open_trades = 8  # новое ограничение совокупных позиций

    # BTC dominance
    use_btcd_filter: bool = True  # можно выключить, если нет фида
    btcd_dom_threshold = DecimalParameter(1.0, 4.0, default=2.0,
                                          space="sell", optimize=True)
    btcd_lookback: int = 24  # кол-во свечей informative_timeframe для расчёта изменения доминанса

    can_short = False
    use_custom_stoploss = True
    position_adjustment_enable = True
    use_exit_signal = True
    ignore_roi_if_exit_signal = True

    max_entry_position_adjustment = 2

    # Базовый стоп‑лосс и параметры динамического ROI
    base_stoploss = DecimalParameter(-0.12, -0.05, default=-0.09,
                                     space="sell", optimize=True)

    use_custom_roi = True
    dynamic_roi_mult = DecimalParameter(1.0, 2.0, default=1.2,
                                        space="sell", optimize=False)
    min_dynamic_roi = DecimalParameter(0.01, 0.03, default=0.015,
                                       space="sell", optimize=False)

    @property
    def stoploss(self) -> float:
        """Базовый стоп‑лосс для стратеги."""
        return self.base_stoploss.value

    def custom_roi(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        trade_duration: int,
        entry_tag: str,
        side: str,
        **kwargs,
    ) -> float:
        """Dynamic ROI based on recent ATR volatility."""
        df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
        if df is not None and "atr_pct" in df.columns:
            atr_pct = df["atr_pct"].iloc[-1]
            return max(atr_pct * self.dynamic_roi_mult.value / 100, self.min_dynamic_roi.value)
        return self.min_dynamic_roi.value

    trailing_stop = False  # конфликтует с custom_stoploss

    # ---- Гипер‑параметры ----------------------------------------------
    buy_min_atr_z = DecimalParameter(1.0, 3.5, default=1.7, space="buy", optimize=True)
    buy_adx_min = IntParameter(22, 38, default=27, space="buy", optimize=True)
    buy_vol_rel_min = DecimalParameter(1.2, 2.0, default=1.5, space="buy", optimize=True)

    atr_window = IntParameter(25, 60, default=28, space="buy", optimize=True)
    # Расширяем диапазон для более частых дозакупок на спокойных активах
    dca_gap_pct = DecimalParameter(0.4, 1.2, default=0.8, space="buy", optimize=True)

    # уровни прибыли и соответствующие им значения stoploss_from_open
    sl_profit_1 = DecimalParameter(0.005, 0.03, default=0.01,
                                  space="sell", optimize=True)
    sl_profit_2 = DecimalParameter(0.01, 0.05, default=0.02,
                                  space="sell", optimize=True)
    sl_profit_3 = DecimalParameter(0.02, 0.08, default=0.04,
                                  space="sell", optimize=True)
    sl_profit_4 = DecimalParameter(0.05, 0.12, default=0.07,
                                  space="sell", optimize=True)
    sl_profit_5 = DecimalParameter(0.08, 0.20, default=0.12,
                                  space="sell", optimize=True)

    sl_stop_1 = DecimalParameter(0.0, 0.01, default=0.0,
                                 space="sell", optimize=True)
    sl_stop_2 = DecimalParameter(0.01, 0.03, default=0.015,
                                 space="sell", optimize=True)
    sl_stop_3 = DecimalParameter(0.02, 0.05, default=0.03,
                                 space="sell", optimize=True)
    sl_stop_4 = DecimalParameter(0.03, 0.07, default=0.05,
                                 space="sell", optimize=True)
    sl_stop_5 = DecimalParameter(0.05, 0.12, default=0.10,
                                 space="sell", optimize=True)

    @property
    def sl_profit_levels(self) -> list:
        return [
            self.sl_profit_1.value,
            self.sl_profit_2.value,
            self.sl_profit_3.value,
            self.sl_profit_4.value,
            self.sl_profit_5.value,
        ]

    @property
    def sl_stop_values(self) -> list:
        return [
            self.sl_stop_1.value,
            self.sl_stop_2.value,
            self.sl_stop_3.value,
            self.sl_stop_4.value,
            self.sl_stop_5.value,
        ]

    # пороги резкой просадки BTC для принудительного выхода
    btc_drop3h_exit = DecimalParameter(-0.10, -0.05, default=-0.07, space="sell", optimize=False)
    btc_drop30m_exit = DecimalParameter(-0.03, -0.01, default=-0.02, space="sell", optimize=False)

    max_trade_minutes = IntParameter(240, 720, default=420, space="sell", optimize=True)

    flat_adx_max = IntParameter(12, 18, default=15, space="sell", optimize=False)

    # -------------------------------------------------------------------
    def protections(self):
        return [
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 48,
                # Более строгий порог по числу сделок
                "trade_limit": 10,
                "stop_duration_candles": 12,
                "max_allowed_drawdown": 0.02,
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

        # ---- Информативные таймфреймы (избегаем lookahead) ----
        pair = metadata["pair"]
        htf_df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.high_tf)
        if htf_df is not None and len(htf_df) > 20:
            if "ema_200" not in htf_df.columns:
                htf_df["ema_200"] = ta.EMA(htf_df, timeperiod=200)
            df = merge_informative_pair(
                df, htf_df, self.timeframe, self.high_tf, ffill=True, suffix="4h"
            )

        # BTC/USDT informative data
        btc_hour = self.dp.get_pair_dataframe(pair="BTC/USDT", timeframe=self.informative_timeframe)
        if btc_hour is not None and len(btc_hour) > 20:
            if "ema_200" not in btc_hour.columns:
                btc_hour["ema_200"] = ta.EMA(btc_hour, timeperiod=200)
            df = merge_informative_pair(
                df, btc_hour, self.timeframe, self.informative_timeframe, ffill=True, suffix="btc"
            )
        btc_fast = self.dp.get_pair_dataframe(pair="BTC/USDT", timeframe=self.btc_fast_tf)
        if btc_fast is not None and len(btc_fast) > 3:
            df = merge_informative_pair(
                df, btc_fast, self.timeframe, self.btc_fast_tf, ffill=True, suffix="btc_fast"
            )
        if self.use_btcd_filter:
            btcd_df = self.dp.get_pair_dataframe(pair="BTC.D", timeframe=self.informative_timeframe)
            if btcd_df is not None and len(btcd_df) > self.btcd_lookback:
                df = merge_informative_pair(
                    df, btcd_df, self.timeframe, self.informative_timeframe, ffill=True, suffix="btcd"
                )

        return df

    # ---- Entry ---------------------------------------------------------
    def _btcd_change_ok(self, df: DataFrame) -> bool:
        if not self.use_btcd_filter:
            return True
        if "close_btcd" not in df.columns or df["close_btcd"].isna().all():
            return False
        if len(df) < self.btcd_lookback:
            return False
        change = (
            df["close_btcd"].iloc[-1] / df["close_btcd"].iloc[-self.btcd_lookback] - 1
        ) * 100
        return change <= self.btcd_dom_threshold.value

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        if not self._btcd_change_ok(df):
            return df
        if "close_4h" not in df.columns or "ema_200_4h" not in df.columns:
            return df
        up_trend = df["close_4h"].iloc[-1] > df["ema_200_4h"].iloc[-1]

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
    def _btcd_exit(self, df: DataFrame) -> bool:
        if not self.use_btcd_filter:
            return False
        if "close_btcd" not in df.columns or df["close_btcd"].isna().all():
            return True
        if len(df) < self.btcd_lookback:
            return True
        change = (
            df["close_btcd"].iloc[-1] / df["close_btcd"].iloc[-self.btcd_lookback] - 1
        ) * 100
        return change > self.btcd_dom_threshold.value

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        if "close_4h" in df.columns and "ema_200_4h" in df.columns:
            global_bear = (df["close_4h"].iloc[-2:] < df["ema_200_4h"].iloc[-2:]).all()
        else:
            global_bear = False

        low_adx = df["adx"].rolling(6).max() < self.flat_adx_max.value

        btcd_exit = self._btcd_exit(df)

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
        df = self.dp.get_pair_dataframe(pair=trade.pair, timeframe=self.timeframe)
        atr_pct = 3.0
        if df is not None and "atr_pct" in df.columns:
            atr_pct = float(df["atr_pct"].iloc[-1])
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
        """Stepped stoploss tightening as trade becomes profitable."""
        base_sl = -0.04 if trade.nr_of_position_adjustments >= 1 else self.base_stoploss.value
        if after_fill:
            return base_sl

        for prof, sl_val in sorted(zip(self.sl_profit_levels, self.sl_stop_values), reverse=True):
            if current_profit > prof:
                return stoploss_from_open(sl_val, current_profit, trade.is_short, trade.leverage)
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
        """Emergency exits triggered by BTC weakness or trade timeout."""
        pair_df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
        needed = {"close_btc", "close_btc_fast", "ema_200_btc", "volume_btc_fast"}
        if (
            pair_df is not None
            and needed.issubset(pair_df.columns)
            and not pair_df[list(needed)].isna().any().any()
        ):
            now_p = pair_df["close_btc"].iloc[-1]
            prev3h_p = pair_df["close_btc"].shift(3).iloc[-1]
            prev30m_p = pair_df["close_btc_fast"].shift(2).iloc[-1]
            drop3h = now_p / prev3h_p - 1
            drop30m = now_p / prev30m_p - 1
            vol = pair_df["volume_btc_fast"].fillna(0)
            vol_spike = vol.iloc[-1] > vol.rolling(8).mean().iloc[-1] * 3
            if (
                now_p < pair_df["ema_200_btc"].iloc[-1]
                or drop3h < self.btc_drop3h_exit.value
                or (drop30m < self.btc_drop30m_exit.value and vol_spike)
            ):
                return "btc_protect"

        lifespan = (current_time - trade.open_date_utc).total_seconds() / 60
        if current_profit < 0.02 and lifespan > self.max_trade_minutes.value:
            return "timeout"

        df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
        if df is not None and len(df) > max(6, self.atr_window.value):
            if df["atr_z"].iloc[-6:].lt(0).all():
                return "atr_compression"
        return None
