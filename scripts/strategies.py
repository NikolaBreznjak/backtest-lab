#!/usr/bin/env python3
"""Causal strategy library + idea generator for Backtest Lab.
All indicators are computed strictly from bars 0..t (no look-ahead).
"""
import calendar
import datetime
import hashlib
import json
import random
from typing import Any

import numpy as np


def _sma(arr: np.ndarray, period: int) -> np.ndarray:
    n = len(arr)
    out = np.full(n, np.nan, dtype=float)
    if period <= 0 or n < period:
        return out
    csum = np.cumsum(np.insert(arr, 0, 0.0))
    out[period - 1 :] = (csum[period:] - csum[:-period]) / period
    return out


def _ema(arr: np.ndarray, period: int) -> np.ndarray:
    n = len(arr)
    out = np.full(n, np.nan, dtype=float)
    if period <= 0 or n < period:
        return out
    alpha = 2.0 / (period + 1.0)
    out[period - 1] = float(np.mean(arr[:period]))
    for i in range(period, n):
        out[i] = alpha * arr[i] + (1.0 - alpha) * out[i - 1]
    return out


def _rolling_std(arr: np.ndarray, period: int) -> np.ndarray:
    n = len(arr)
    out = np.full(n, np.nan, dtype=float)
    if period <= 1 or n < period:
        return out
    for i in range(period - 1, n):
        out[i] = float(np.std(arr[i - period + 1 : i + 1], ddof=0))
    return out


def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    n = len(close)
    tr = np.empty(n, dtype=float)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    out = np.full(n, np.nan, dtype=float)
    if n < period:
        return out
    out[period - 1] = float(np.mean(tr[:period]))
    for i in range(period, n):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def _rsi(close: np.ndarray, period: int) -> np.ndarray:
    n = len(close)
    out = np.full(n, np.nan, dtype=float)
    if n <= period:
        return out
    deltas = np.diff(close)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))
    if avg_loss == 0:
        out[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        out[period] = 100.0 - (100.0 / (1.0 + rs))
    for i in range(period + 1, n):
        g = gains[i - 1]
        l = losses[i - 1]
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
        if avg_loss == 0:
            out[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[i] = 100.0 - (100.0 / (1.0 + rs))
    return out


def compute_strategy(bars: list[dict], family: str, params: dict[str, Any]) -> dict:
    """Return causal target_pos (0/1 array at bar close), warmup index, and chart indicator series."""
    n = len(bars)
    dates = [b["date"] for b in bars]
    high = np.array([b["high"] for b in bars], dtype=float)
    low = np.array([b["low"] for b in bars], dtype=float)
    close = np.array([b["close"] for b in bars], dtype=float)
    sig = np.zeros(n, dtype=int)

    if family == "sma_cross":
        fast_p = int(params["fast"])
        slow_p = int(params["slow"])
        fast = _sma(close, fast_p)
        slow = _sma(close, slow_p)
        warmup = slow_p
        for i in range(warmup, n):
            if fast[i] > slow[i]:
                sig[i] = 1
        indicators = {
            "pane": "price",
            "series": [
                {"name": f"SMA({fast_p})", "color": "#00d395", "values": fast},
                {"name": f"SMA({slow_p})", "color": "#f5a623", "values": slow},
            ],
        }

    elif family == "ema_cross":
        fast_p = int(params["fast"])
        slow_p = int(params["slow"])
        fast = _ema(close, fast_p)
        slow = _ema(close, slow_p)
        warmup = slow_p
        for i in range(warmup, n):
            if fast[i] > slow[i]:
                sig[i] = 1
        indicators = {
            "pane": "price",
            "series": [
                {"name": f"EMA({fast_p})", "color": "#38bdf8", "values": fast},
                {"name": f"EMA({slow_p})", "color": "#fb7185", "values": slow},
            ],
        }

    elif family == "rsi_reversion":
        period = int(params["period"])
        oversold = float(params["oversold"])
        overbought = float(params["overbought"])
        rsi = _rsi(close, period)
        warmup = period + 1
        pos = 0
        for i in range(warmup, n):
            if pos == 0 and rsi[i] <= oversold:
                pos = 1
            elif pos == 1 and rsi[i] >= overbought:
                pos = 0
            sig[i] = pos
        indicators = {
            "pane": "sub",
            "label": f"RSI({period})",
            "levels": [oversold, overbought],
            "series": [{"name": f"RSI({period})", "color": "#a78bfa", "values": rsi}],
        }

    elif family == "bollinger":
        period = int(params["period"])
        num_std = float(params["num_std"])
        mode = params.get("mode", "reversion")
        mid = _sma(close, period)
        sd = _rolling_std(close, period)
        upper = mid + num_std * sd
        lower = mid - num_std * sd
        warmup = period
        pos = 0
        for i in range(warmup, n):
            if mode == "reversion":
                if pos == 0 and close[i] < lower[i]:
                    pos = 1
                elif pos == 1 and close[i] >= mid[i]:
                    pos = 0
            else:  # breakout
                if pos == 0 and close[i] > upper[i]:
                    pos = 1
                elif pos == 1 and close[i] < mid[i]:
                    pos = 0
            sig[i] = pos
        indicators = {
            "pane": "price",
            "series": [
                {"name": f"BB Upper({period},{num_std})", "color": "#fb7185", "values": upper},
                {"name": f"BB Mid({period})", "color": "#94a3b8", "values": mid},
                {"name": f"BB Lower({period},{num_std})", "color": "#00d395", "values": lower},
            ],
        }

    elif family == "donchian":
        entry_len = int(params["entry_len"])
        exit_len = int(params["exit_len"])
        upper = np.full(n, np.nan, dtype=float)
        lower = np.full(n, np.nan, dtype=float)
        warmup = max(entry_len, exit_len)
        pos = 0
        for i in range(warmup, n):
            up = float(np.max(high[i - entry_len : i]))
            lo = float(np.min(low[i - exit_len : i]))
            upper[i] = up
            lower[i] = lo
            if pos == 0 and close[i] > up:
                pos = 1
            elif pos == 1 and close[i] < lo:
                pos = 0
            sig[i] = pos
        indicators = {
            "pane": "price",
            "series": [
                {"name": f"Donchian High({entry_len})", "color": "#38bdf8", "values": upper},
                {"name": f"Donchian Low({exit_len})", "color": "#f59e0b", "values": lower},
            ],
        }

    elif family == "supertrend":
        period = int(params["atr_period"])
        mult = float(params["multiplier"])
        atr = _atr(high, low, close, period)
        hl2 = (high + low) / 2.0
        upper_band = hl2 + mult * atr
        lower_band = hl2 - mult * atr
        final_upper = np.copy(upper_band)
        final_lower = np.copy(lower_band)
        st = np.full(n, np.nan, dtype=float)
        direction = np.ones(n, dtype=int)
        warmup = period + 1
        for i in range(period, n):
            if i == period:
                final_upper[i] = upper_band[i]
                final_lower[i] = lower_band[i]
                direction[i] = 1 if close[i] >= final_upper[i] else -1
                st[i] = final_lower[i] if direction[i] == 1 else final_upper[i]
                continue
            final_upper[i] = (
                upper_band[i]
                if (upper_band[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1])
                else final_upper[i - 1]
            )
            final_lower[i] = (
                lower_band[i]
                if (lower_band[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1])
                else final_lower[i - 1]
            )
            if direction[i - 1] == 1:
                direction[i] = -1 if close[i] < final_lower[i] else 1
            else:
                direction[i] = 1 if close[i] > final_upper[i] else -1
            st[i] = final_lower[i] if direction[i] == 1 else final_upper[i]
            if i >= warmup and direction[i] == 1:
                sig[i] = 1
        indicators = {
            "pane": "price",
            "series": [{"name": f"Supertrend({period},{mult})", "color": "#00d395", "values": st}],
        }

    elif family == "parabolic_sar":
        af_start = float(params["af_start"])
        af_step = float(params["af_step"])
        af_max = float(params["af_max"])
        sar = np.full(n, np.nan, dtype=float)
        warmup = 5
        uptrend = True
        ep = high[0]
        af = af_start
        sar_val = low[0]
        sar[0] = sar_val
        for i in range(1, n):
            prev_sar = sar_val
            if uptrend:
                sar_val = prev_sar + af * (ep - prev_sar)
                sar_val = min(sar_val, low[i - 1])
                if i >= 2:
                    sar_val = min(sar_val, low[i - 2])
                if low[i] < sar_val:
                    uptrend = False
                    sar_val = ep
                    ep = low[i]
                    af = af_start
                else:
                    if high[i] > ep:
                        ep = high[i]
                        af = min(af_max, af + af_step)
            else:
                sar_val = prev_sar + af * (ep - prev_sar)
                sar_val = max(sar_val, high[i - 1])
                if i >= 2:
                    sar_val = max(sar_val, high[i - 2])
                if high[i] > sar_val:
                    uptrend = True
                    sar_val = ep
                    ep = high[i]
                    af = af_start
                else:
                    if low[i] < ep:
                        ep = low[i]
                        af = min(af_max, af + af_step)
            sar[i] = sar_val
            if i >= warmup and uptrend:
                sig[i] = 1
        indicators = {
            "pane": "price",
            "series": [{"name": f"PSAR({af_start},{af_step},{af_max})", "color": "#f472b6", "values": sar}],
        }

    elif family == "adx_dmi":
        period = int(params["period"])
        adx_thresh = float(params["adx_threshold"])
        up_move = np.zeros(n)
        down_move = np.zeros(n)
        tr = np.zeros(n)
        tr[0] = high[0] - low[0]
        for i in range(1, n):
            up = high[i] - high[i - 1]
            dn = low[i - 1] - low[i]
            up_move[i] = up if (up > dn and up > 0) else 0.0
            down_move[i] = dn if (dn > up and dn > 0) else 0.0
            tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
        sm_tr = np.full(n, np.nan)
        sm_up = np.full(n, np.nan)
        sm_dn = np.full(n, np.nan)
        plus_di = np.full(n, np.nan)
        minus_di = np.full(n, np.nan)
        dx = np.full(n, np.nan)
        adx = np.full(n, np.nan)
        sm_tr[period] = float(np.sum(tr[1 : period + 1]))
        sm_up[period] = float(np.sum(up_move[1 : period + 1]))
        sm_dn[period] = float(np.sum(down_move[1 : period + 1]))
        for i in range(period + 1, n):
            sm_tr[i] = sm_tr[i - 1] - (sm_tr[i - 1] / period) + tr[i]
            sm_up[i] = sm_up[i - 1] - (sm_up[i - 1] / period) + up_move[i]
            sm_dn[i] = sm_dn[i - 1] - (sm_dn[i - 1] / period) + down_move[i]
        for i in range(period, n):
            if sm_tr[i] and sm_tr[i] > 0:
                plus_di[i] = 100.0 * sm_up[i] / sm_tr[i]
                minus_di[i] = 100.0 * sm_dn[i] / sm_tr[i]
                denom = plus_di[i] + minus_di[i]
                dx[i] = 100.0 * abs(plus_di[i] - minus_di[i]) / denom if denom > 0 else 0.0
        start_adx = 2 * period - 1
        if start_adx < n:
            adx[start_adx] = float(np.nanmean(dx[period : start_adx + 1]))
            for i in range(start_adx + 1, n):
                adx[i] = ((adx[i - 1] * (period - 1)) + dx[i]) / period
        warmup = 2 * period
        for i in range(warmup, n):
            if not np.isnan(adx[i]) and adx[i] >= adx_thresh and plus_di[i] > minus_di[i]:
                sig[i] = 1
        indicators = {
            "pane": "sub",
            "label": f"ADX/DMI({period})",
            "levels": [adx_thresh],
            "series": [
                {"name": f"ADX({period})", "color": "#f5a623", "values": adx},
                {"name": "+DI", "color": "#00d395", "values": plus_di},
                {"name": "-DI", "color": "#ff4d6a", "values": minus_di},
            ],
        }

    elif family == "cci":
        period = int(params["period"])
        entry_lvl = float(params["entry_level"])
        exit_lvl = float(params["exit_level"])
        mode = params.get("mode", "trend")
        tp = (high + low + close) / 3.0
        sma_tp = _sma(tp, period)
        cci = np.full(n, np.nan, dtype=float)
        for i in range(period - 1, n):
            mad = float(np.mean(np.abs(tp[i - period + 1 : i + 1] - sma_tp[i])))
            cci[i] = (tp[i] - sma_tp[i]) / (0.015 * mad) if mad > 0 else 0.0
        warmup = period
        pos = 0
        for i in range(warmup, n):
            if mode == "trend":
                if pos == 0 and cci[i] > entry_lvl:
                    pos = 1
                elif pos == 1 and cci[i] < exit_lvl:
                    pos = 0
            else:
                if pos == 0 and cci[i] < -abs(entry_lvl):
                    pos = 1
                elif pos == 1 and cci[i] > exit_lvl:
                    pos = 0
            sig[i] = pos
        indicators = {
            "pane": "sub",
            "label": f"CCI({period})",
            "levels": [entry_lvl, exit_lvl, -abs(entry_lvl)],
            "series": [{"name": f"CCI({period})", "color": "#38bdf8", "values": cci}],
        }

    elif family == "aroon":
        period = int(params["period"])
        threshold = float(params["threshold"])
        aroon_up = np.full(n, np.nan, dtype=float)
        aroon_dn = np.full(n, np.nan, dtype=float)
        warmup = period
        for i in range(warmup, n):
            h_win = high[i - period : i + 1]
            l_win = low[i - period : i + 1]
            days_since_high = period - int(np.argmax(h_win))
            days_since_low = period - int(np.argmin(l_win))
            aroon_up[i] = 100.0 * (period - days_since_high) / period
            aroon_dn[i] = 100.0 * (period - days_since_low) / period
            if aroon_up[i] > aroon_dn[i] and aroon_up[i] >= threshold:
                sig[i] = 1
        indicators = {
            "pane": "sub",
            "label": f"Aroon({period})",
            "levels": [threshold],
            "series": [
                {"name": "Aroon Up", "color": "#00d395", "values": aroon_up},
                {"name": "Aroon Down", "color": "#ff4d6a", "values": aroon_dn},
            ],
        }

    elif family == "stochastic":
        k_p = int(params["k_period"])
        d_p = int(params["d_period"])
        oversold = float(params["oversold"])
        overbought = float(params["overbought"])
        k_val = np.full(n, np.nan, dtype=float)
        for i in range(k_p - 1, n):
            hh = float(np.max(high[i - k_p + 1 : i + 1]))
            ll = float(np.min(low[i - k_p + 1 : i + 1]))
            k_val[i] = 100.0 * (close[i] - ll) / (hh - ll) if hh > ll else 50.0
        d_val = np.full(n, np.nan, dtype=float)
        for i in range(k_p + d_p - 2, n):
            d_val[i] = float(np.mean(k_val[i - d_p + 1 : i + 1]))
        warmup = k_p + d_p
        pos = 0
        for i in range(warmup, n):
            if pos == 0 and k_val[i] <= oversold and k_val[i] > d_val[i]:
                pos = 1
            elif pos == 1 and k_val[i] >= overbought:
                pos = 0
            sig[i] = pos
        indicators = {
            "pane": "sub",
            "label": f"Stoch({k_p},{d_p})",
            "levels": [oversold, overbought],
            "series": [
                {"name": "%K", "color": "#38bdf8", "values": k_val},
                {"name": "%D", "color": "#f5a623", "values": d_val},
            ],
        }

    elif family == "zscore_reversion":
        period = int(params["period"])
        entry_z = float(params["entry_z"])
        exit_z = float(params["exit_z"])
        mean = _sma(close, period)
        sd = _rolling_std(close, period)
        z = np.full(n, np.nan, dtype=float)
        for i in range(period - 1, n):
            z[i] = (close[i] - mean[i]) / sd[i] if sd[i] > 0 else 0.0
        warmup = period
        pos = 0
        for i in range(warmup, n):
            if pos == 0 and z[i] <= -abs(entry_z):
                pos = 1
            elif pos == 1 and z[i] >= exit_z:
                pos = 0
            sig[i] = pos
        indicators = {
            "pane": "sub",
            "label": f"Z-Score({period})",
            "levels": [-abs(entry_z), exit_z],
            "series": [{"name": f"Z({period})", "color": "#c084fc", "values": z}],
        }

    elif family == "turn_of_month":
        days_before = int(params["days_before_eom"])
        days_into = int(params["days_into_bom"])
        warmup = 5
        cal_flag = np.full(n, 0.0, dtype=float)
        for i, d_str in enumerate(dates):
            dt = datetime.date.fromisoformat(d_str)
            # Count remaining weekdays (Mon-Fri) in this month after dt (strictly calendar-known)
            last_dom = calendar.monthrange(dt.year, dt.month)[1]
            rem_weekdays = sum(
                1
                for day in range(dt.day + 1, last_dom + 1)
                if datetime.date(dt.year, dt.month, day).weekday() < 5
            )
            elapsed_weekdays = sum(
                1
                for day in range(1, dt.day + 1)
                if datetime.date(dt.year, dt.month, day).weekday() < 5
            )
            # Signal at close of bar i sets position for bar i+1.
            # Enter near end-of-month, hold through first `days_into` weekdays of new month.
            in_tom = (rem_weekdays < days_before) or (elapsed_weekdays < days_into)
            cal_flag[i] = 1.0 if in_tom else 0.0
            if i >= warmup and in_tom:
                sig[i] = 1
        indicators = {
            "pane": "sub",
            "label": f"TOM(-{days_before}/+{days_into})",
            "levels": [0.5],
            "series": [{"name": "TOM Window", "color": "#00d395", "values": cal_flag}],
        }

    else:
        raise ValueError(f"Unknown strategy family: {family}")

    return {
        "signals": sig,
        "warmup": max(warmup, 20),
        "indicators": indicators,
    }


def strategy_id(family: str, params: dict[str, Any]) -> str:
    canonical = json.dumps({"family": family, "params": params}, sort_keys=True)
    digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:8]
    return f"{family}_{digest}"


def format_strategy_name(family: str, params: dict[str, Any]) -> str:
    p_str = ", ".join(f"{k}={v}" for k, v in params.items())
    labels = {
        "sma_cross": "SMA Cross",
        "ema_cross": "EMA Cross",
        "rsi_reversion": "RSI Reversion",
        "bollinger": "Bollinger",
        "donchian": "Donchian Breakout",
        "supertrend": "Supertrend",
        "parabolic_sar": "Parabolic SAR",
        "adx_dmi": "ADX / DMI",
        "cci": "CCI",
        "aroon": "Aroon",
        "stochastic": "Stochastic",
        "zscore_reversion": "Z-Score Reversion",
        "turn_of_month": "Turn-of-Month",
    }
    return f"{labels.get(family, family)} ({p_str})"


BASELINE_CATALOG = [
    ("sma_cross", {"fast": 20, "slow": 50}),
    ("sma_cross", {"fast": 50, "slow": 200}),
    ("ema_cross", {"fast": 12, "slow": 26}),
    ("ema_cross", {"fast": 21, "slow": 55}),
    ("rsi_reversion", {"period": 14, "oversold": 30, "overbought": 70}),
    ("rsi_reversion", {"period": 7, "oversold": 25, "overbought": 65}),
    ("bollinger", {"period": 20, "num_std": 2.0, "mode": "reversion"}),
    ("bollinger", {"period": 20, "num_std": 2.0, "mode": "breakout"}),
    ("donchian", {"entry_len": 20, "exit_len": 10}),
    ("donchian", {"entry_len": 55, "exit_len": 20}),
    ("supertrend", {"atr_period": 10, "multiplier": 3.0}),
    ("supertrend", {"atr_period": 14, "multiplier": 2.5}),
    ("parabolic_sar", {"af_start": 0.02, "af_step": 0.02, "af_max": 0.2}),
    ("adx_dmi", {"period": 14, "adx_threshold": 20}),
    ("adx_dmi", {"period": 14, "adx_threshold": 25}),
    ("cci", {"period": 20, "entry_level": 100, "exit_level": 0, "mode": "trend"}),
    ("cci", {"period": 20, "entry_level": 100, "exit_level": 0, "mode": "reversion"}),
    ("aroon", {"period": 25, "threshold": 70}),
    ("stochastic", {"k_period": 14, "d_period": 3, "oversold": 20, "overbought": 80}),
    ("zscore_reversion", {"period": 20, "entry_z": 2.0, "exit_z": 0.0}),
    ("turn_of_month", {"days_before_eom": 2, "days_into_bom": 3}),
]


def sample_random_idea(rng: random.Random) -> tuple[str, dict[str, Any]]:
    family = rng.choice([
        "sma_cross", "ema_cross", "rsi_reversion", "bollinger",
        "donchian", "supertrend", "parabolic_sar", "adx_dmi",
        "cci", "aroon", "stochastic", "zscore_reversion", "turn_of_month",
    ])
    if family in ("sma_cross", "ema_cross"):
        fast = rng.choice([5, 8, 10, 12, 15, 20, 30, 40])
        slow = rng.choice([25, 35, 50, 75, 100, 120, 150, 200])
        if fast >= slow:
            slow = fast + rng.choice([15, 30, 50])
        return family, {"fast": fast, "slow": slow}
    if family == "rsi_reversion":
        return family, {
            "period": rng.choice([5, 7, 10, 14, 21]),
            "oversold": rng.choice([20, 25, 30, 35, 40]),
            "overbought": rng.choice([55, 60, 65, 70, 75, 80]),
        }
    if family == "bollinger":
        return family, {
            "period": rng.choice([10, 15, 20, 30, 40]),
            "num_std": rng.choice([1.5, 1.75, 2.0, 2.25, 2.5]),
            "mode": rng.choice(["reversion", "breakout"]),
        }
    if family == "donchian":
        entry_len = rng.choice([10, 15, 20, 30, 40, 55, 70])
        exit_len = rng.choice([5, 8, 10, 15, 20, 25])
        if exit_len >= entry_len:
            exit_len = max(5, entry_len // 2)
        return family, {"entry_len": entry_len, "exit_len": exit_len}
    if family == "supertrend":
        return family, {
            "atr_period": rng.choice([7, 10, 14, 20]),
            "multiplier": rng.choice([1.5, 2.0, 2.5, 3.0, 3.5, 4.0]),
        }
    if family == "parabolic_sar":
        af_start = rng.choice([0.01, 0.015, 0.02, 0.03])
        af_step = rng.choice([0.01, 0.02, 0.025, 0.03])
        af_max = rng.choice([0.15, 0.2, 0.25, 0.3])
        return family, {"af_start": af_start, "af_step": af_step, "af_max": af_max}
    if family == "adx_dmi":
        return family, {
            "period": rng.choice([7, 10, 14, 20, 28]),
            "adx_threshold": rng.choice([15, 18, 20, 25, 30]),
        }
    if family == "cci":
        return family, {
            "period": rng.choice([10, 14, 20, 30]),
            "entry_level": rng.choice([75, 100, 125, 150]),
            "exit_level": rng.choice([-50, 0, 50]),
            "mode": rng.choice(["trend", "reversion"]),
        }
    if family == "aroon":
        return family, {
            "period": rng.choice([10, 14, 20, 25, 35]),
            "threshold": rng.choice([50, 60, 70, 80]),
        }
    if family == "stochastic":
        return family, {
            "k_period": rng.choice([7, 10, 14, 21]),
            "d_period": rng.choice([3, 5]),
            "oversold": rng.choice([15, 20, 25, 30, 35]),
            "overbought": rng.choice([65, 70, 75, 80, 85]),
        }
    if family == "zscore_reversion":
        return family, {
            "period": rng.choice([10, 15, 20, 30, 45]),
            "entry_z": rng.choice([1.25, 1.5, 1.75, 2.0, 2.5]),
            "exit_z": rng.choice([-0.5, 0.0, 0.5, 1.0]),
        }
    # turn_of_month
    return "turn_of_month", {
        "days_before_eom": rng.choice([1, 2, 3, 4, 5]),
        "days_into_bom": rng.choice([1, 2, 3, 4, 5, 6]),
    }


def generate_ideas(existing_ids: set[str], total_new: int = 26, seed: int | None = None) -> list[dict]:
    """Generate baseline templates (if untested) + fresh randomized parameter combos."""
    rng = random.Random(seed)
    ideas = []
    seen = set(existing_ids)

    # First include untested baseline templates
    for family, params in BASELINE_CATALOG:
        sid = strategy_id(family, params)
        if sid not in seen:
            seen.add(sid)
            ideas.append({
                "id": sid,
                "family": family,
                "params": params,
                "name": format_strategy_name(family, params),
                "origin": "template",
            })
        if len(ideas) >= total_new:
            return ideas

    # Fill remaining quota with fresh randomized parameter combos
    attempts = 0
    while len(ideas) < total_new and attempts < 500:
        attempts += 1
        family, params = sample_random_idea(rng)
        sid = strategy_id(family, params)
        if sid not in seen:
            seen.add(sid)
            ideas.append({
                "id": sid,
                "family": family,
                "params": params,
                "name": format_strategy_name(family, params),
                "origin": "randomized",
            })
    return ideas
