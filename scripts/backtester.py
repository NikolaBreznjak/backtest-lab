#!/usr/bin/env python3
"""Single-convention backtester, 4 stress tests, and default-reject judge."""
import math
from typing import Any

import numpy as np

FEE_BPS_BASELINE = 2.0
FEE_SWEEP_BPS = [2.0, 5.0, 10.0, 20.0]
ROLLING_STEP_DAYS = 21
ROLLING_MIN_DAYS = 252
TRAIN_FRAC = 0.60
MC_TRIALS = 200


def _sharpe_from_curve(curve: np.ndarray) -> float:
    if len(curve) < 10:
        return 0.0
    rets = curve[1:] / curve[:-1] - 1.0
    sd = float(np.std(rets, ddof=1))
    if sd <= 1e-12 or not math.isfinite(sd):
        return 0.0
    return float(np.mean(rets) / sd * math.sqrt(252.0))


def _max_dd_pct(curve: np.ndarray) -> float:
    if len(curve) == 0:
        return 0.0
    peaks = np.maximum.accumulate(curve)
    dd = (curve / peaks) - 1.0
    return float(np.min(dd) * 100.0)


def simulate_window(
    opens: np.ndarray,
    closes: np.ndarray,
    dates: list[str] | None,
    target_pos: np.ndarray,
    fee_bps: float,
    start_idx: int,
    end_idx: int,
    include_details: bool = False,
) -> dict[str, Any]:
    """Simulate long-only execution:
    - Signal decided at bar t close takes effect at bar t+1 open.
    - Fees applied per side (entry and exit).
    """
    fee = fee_bps * 1e-4
    w_open = opens[start_idx : end_idx + 1]
    w_close = closes[start_idx : end_idx + 1]
    m = len(w_close)
    if m < 5:
        raise ValueError("Simulation window too short")

    desired = np.zeros(m, dtype=int)
    # Signal from bar t close governs bar t+1 position
    desired[1:] = target_pos[start_idx:end_idx]

    prev_desired = np.zeros(m, dtype=int)
    prev_desired[1:] = desired[:-1]

    entered = (desired == 1) & (prev_desired == 0)
    held = (desired == 1) & (prev_desired == 1)
    exited = (desired == 0) & (prev_desired == 1)

    daily_mult = np.ones(m, dtype=float)
    daily_mult[entered] = w_close[entered] / (w_open[entered] * (1.0 + fee))
    if np.any(held):
        held_idx = np.where(held)[0]
        daily_mult[held_idx] = w_close[held_idx] / w_close[held_idx - 1]
    if np.any(exited):
        exit_idx = np.where(exited)[0]
        daily_mult[exit_idx] = (w_open[exit_idx] * (1.0 - fee)) / w_close[exit_idx - 1]

    eq_curve = np.cumprod(daily_mult)
    # Net terminal liquidation if still in position at final bar
    terminal_eq = float(eq_curve[-1] * (1.0 - fee if desired[-1] == 1 else 1.0))

    # Buy & Hold over exact same window [start_idx .. end_idx]
    bh_curve = w_close / (w_open[0] * (1.0 + fee))
    bh_terminal = float(bh_curve[-1] * (1.0 - fee))

    total_ret = (terminal_eq - 1.0) * 100.0
    bh_ret = (bh_terminal - 1.0) * 100.0
    years = max((m - 1) / 252.0, 1e-6)
    cagr = ((max(terminal_eq, 1e-9) ** (1.0 / years)) - 1.0) * 100.0
    bh_cagr = ((max(bh_terminal, 1e-9) ** (1.0 / years)) - 1.0) * 100.0

    sharpe = _sharpe_from_curve(eq_curve)
    bh_sharpe = _sharpe_from_curve(bh_curve)
    max_dd = _max_dd_pct(eq_curve)
    bh_max_dd = _max_dd_pct(bh_curve)
    exposure = float(np.mean(desired[1:]) * 100.0)
    n_entries = int(np.sum(entered))

    out: dict[str, Any] = {
        "total_return_pct": round(total_ret, 2),
        "bh_return_pct": round(bh_ret, 2),
        "excess_return_pct": round(total_ret - bh_ret, 2),
        "cagr_pct": round(cagr, 2),
        "bh_cagr_pct": round(bh_cagr, 2),
        "sharpe": round(sharpe, 3),
        "bh_sharpe": round(bh_sharpe, 3),
        "max_drawdown_pct": round(max_dd, 2),
        "bh_max_drawdown_pct": round(bh_max_dd, 2),
        "trades": n_entries,
        "exposure_pct": round(exposure, 1),
        "beats_bh_return": bool(total_ret > bh_ret),
        "beats_bh_sharpe": bool(sharpe > bh_sharpe),
    }

    if include_details:
        entry_indices = np.where(entered)[0]
        exit_indices = np.where(exited)[0]
        trade_records = []
        wins = 0
        gross_win = 0.0
        gross_loss = 0.0
        hold_days = []

        for k, ei in enumerate(entry_indices):
            abs_entry = start_idx + int(ei)
            entry_px = float(w_open[ei] * (1.0 + fee))
            if k < len(exit_indices):
                xi = int(exit_indices[k])
                abs_exit = start_idx + xi
                exit_px = float(w_open[xi] * (1.0 - fee))
                is_open = False
                bars_held = xi - int(ei)
            else:
                abs_exit = end_idx
                exit_px = float(w_close[-1] * (1.0 - fee))
                is_open = True
                bars_held = (m - 1) - int(ei)

            t_ret = (exit_px / entry_px - 1.0) * 100.0
            hold_days.append(max(bars_held, 1))
            if t_ret > 0:
                wins += 1
                gross_win += t_ret
            else:
                gross_loss += abs(t_ret)

            trade_records.append({
                "entry_idx": abs_entry,
                "exit_idx": abs_exit,
                "entry_date": dates[abs_entry] if dates else "",
                "exit_date": dates[abs_exit] if dates else "",
                "entry_price": round(float(w_open[ei]), 2),
                "exit_price": round(float(w_close[-1] if is_open else w_open[xi]), 2),
                "return_pct": round(t_ret, 2),
                "bars_held": max(bars_held, 1),
                "open": is_open,
            })

        win_rate = (wins / len(trade_records) * 100.0) if trade_records else 0.0
        pf = (gross_win / gross_loss) if gross_loss > 1e-9 else (99.0 if gross_win > 0 else 0.0)
        avg_hold = float(np.mean(hold_days)) if hold_days else 0.0

        out["win_rate_pct"] = round(win_rate, 1)
        out["profit_factor"] = round(min(pf, 99.0), 2)
        out["avg_hold_days"] = round(avg_hold, 1)
        out["trade_list"] = trade_records
        out["equity_curve"] = [round(float(x), 4) for x in eq_curve]
        out["bh_curve"] = [round(float(x), 4) for x in bh_curve]
        out["start_idx"] = int(start_idx)
        out["end_idx"] = int(end_idx)

    return out


def _random_signals_same_exposure(
    n_total: int,
    start_idx: int,
    end_idx: int,
    exposure_frac: float,
    avg_hold_days: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Generate random 0/1 signal sequence on [start_idx..end_idx] matching exposure & hold length."""
    sig = np.zeros(n_total, dtype=int)
    p = min(max(exposure_frac, 0.02), 0.98)
    mean_hold = max(avg_hold_days, 2.0)
    p_exit = min(max(1.0 / mean_hold, 0.01), 0.50)
    # Steady-state Markov chain: p = p_enter / (p_enter + p_exit) => p_enter = p * p_exit / (1 - p)
    p_enter = min(max(p * p_exit / max(1.0 - p, 1e-6), 0.002), 0.50)

    state = 1 if rng.random() < p else 0
    u = rng.random(end_idx - start_idx + 1)
    for k in range(len(u)):
        if state == 0:
            if u[k] < p_enter:
                state = 1
        else:
            if u[k] < p_exit:
                state = 0
        sig[start_idx + k] = state
    return sig


def evaluate_idea_on_universe(
    idea: dict[str, Any],
    market_data: dict[str, dict[str, Any]],
    compute_fn,
    mc_seed: int = 42,
) -> dict[str, Any]:
    """Run baseline + all 4 stress tests across all 4 markets and return judge verdict."""
    family = idea["family"]
    params = idea["params"]
    symbols = list(market_data.keys())

    per_market = {}
    pre_signals = {}
    warmups = {}

    for sym in symbols:
        m = market_data[sym]
        res = compute_fn(m["bars"], family, params)
        pre_signals[sym] = res["signals"]
        warmups[sym] = res["warmup"]

        start_idx = res["warmup"]
        end_idx = len(m["bars"]) - 1
        base = simulate_window(
            m["opens"], m["closes"], m["dates"],
            res["signals"], FEE_BPS_BASELINE, start_idx, end_idx,
            include_details=True,
        )
        per_market[sym] = base

    # Baseline universe aggregates
    mean_ret = float(np.mean([per_market[s]["total_return_pct"] for s in symbols]))
    mean_bh_ret = float(np.mean([per_market[s]["bh_return_pct"] for s in symbols]))
    mean_excess = float(np.mean([per_market[s]["excess_return_pct"] for s in symbols]))
    mean_sharpe = float(np.mean([per_market[s]["sharpe"] for s in symbols]))
    mean_bh_sharpe = float(np.mean([per_market[s]["bh_sharpe"] for s in symbols]))
    mean_cagr = float(np.mean([per_market[s]["cagr_pct"] for s in symbols]))
    mean_dd = float(np.mean([per_market[s]["max_drawdown_pct"] for s in symbols]))
    mean_trades = float(np.mean([per_market[s]["trades"] for s in symbols]))
    min_trades_mkt = min(per_market[s]["trades"] for s in symbols)
    mean_exposure = float(np.mean([per_market[s]["exposure_pct"] for s in symbols]))
    mean_win_rate = float(np.mean([per_market[s]["win_rate_pct"] for s in symbols]))

    # Pre-check: minimum activity & realism bounds
    precheck_reasons = []
    if mean_trades < 10 or min_trades_mkt < 6:
        precheck_reasons.append(f"Too few trades (mean={mean_trades:.1f} < 10 or min_mkt={min_trades_mkt} < 6)")
    if mean_exposure < 10.0 or mean_exposure > 92.0:
        precheck_reasons.append(f"Exposure out of bounds ({mean_exposure:.1f}%, require 10%..92%)")

    # ---------------- STRESS TEST 1: FEE SWEEP (2, 5, 10, 20 bps) ----------------
    fee_sweep = []
    for bps in FEE_SWEEP_BPS:
        mkt_res = []
        for sym in symbols:
            m = market_data[sym]
            r = simulate_window(
                m["opens"], m["closes"], None,
                pre_signals[sym], bps, warmups[sym], len(m["bars"]) - 1,
                include_details=False,
            )
            mkt_res.append(r)
        fee_sweep.append({
            "fee_bps": bps,
            "mean_return_pct": round(float(np.mean([x["total_return_pct"] for x in mkt_res])), 2),
            "mean_cagr_pct": round(float(np.mean([x["cagr_pct"] for x in mkt_res])), 2),
            "mean_sharpe": round(float(np.mean([x["sharpe"] for x in mkt_res])), 3),
            "beats_bh_count": sum(1 for x in mkt_res if x["beats_bh_return"] or x["beats_bh_sharpe"]),
        })

    f2 = fee_sweep[0]
    f10 = fee_sweep[2]
    f20 = fee_sweep[3]
    sharpe_retention_10 = (f10["mean_sharpe"] / f2["mean_sharpe"]) if f2["mean_sharpe"] > 0 else 0.0
    test1_reasons = []
    if f2["beats_bh_count"] < 2:
        test1_reasons.append(f"At 2 bps, beat B&H on only {f2['beats_bh_count']}/4 markets (need >=2)")
    if f10["mean_cagr_pct"] <= 0.0 or f10["mean_sharpe"] < 0.50 or sharpe_retention_10 < 0.65:
        test1_reasons.append(
            f"At 10 bps, CAGR={f10['mean_cagr_pct']:.1f}%, Sharpe={f10['mean_sharpe']:.2f}, retention={sharpe_retention_10:.2f}"
        )
    if f20["mean_return_pct"] <= 0.0:
        test1_reasons.append(f"At 20 bps, mean return {f20['mean_return_pct']:.1f}% <= 0%")
    test1_pass = len(test1_reasons) == 0

    # ---------------- STRESS TEST 2: EVERY START DATE (ROLLING STARTS) ----------------
    roll_returns = []
    roll_beat_bh = []
    for sym in symbols:
        m = market_data[sym]
        n_bars = len(m["bars"])
        s0 = warmups[sym]
        for s_idx in range(s0, n_bars - ROLLING_MIN_DAYS, ROLLING_STEP_DAYS):
            r = simulate_window(
                m["opens"], m["closes"], None,
                pre_signals[sym], FEE_BPS_BASELINE, s_idx, n_bars - 1,
                include_details=False,
            )
            roll_returns.append(r["total_return_pct"])
            roll_beat_bh.append(1 if (r["beats_bh_sharpe"] or r["beats_bh_return"]) else 0)

    pct_positive_roll = float(np.mean([1 if x > 0 else 0 for x in roll_returns]) * 100.0) if roll_returns else 0.0
    pct_beat_bh_roll = float(np.mean(roll_beat_bh) * 100.0) if roll_beat_bh else 0.0
    test2_reasons = []
    if pct_positive_roll < 65.0:
        test2_reasons.append(f"Only {pct_positive_roll:.1f}% rolling starts positive (need >=65%)")
    if pct_beat_bh_roll < 50.0:
        test2_reasons.append(f"Beat B&H on only {pct_beat_bh_roll:.1f}% rolling starts (need >=50%)")
    test2_pass = len(test2_reasons) == 0
    rolling_summary = {
        "windows_tested": len(roll_returns),
        "pct_positive": round(pct_positive_roll, 1),
        "pct_beat_bh": round(pct_beat_bh_roll, 1),
        "median_return_pct": round(float(np.median(roll_returns)) if roll_returns else 0.0, 2),
        "worst_return_pct": round(float(np.min(roll_returns)) if roll_returns else 0.0, 2),
        "best_return_pct": round(float(np.max(roll_returns)) if roll_returns else 0.0, 2),
        "passed": test2_pass,
    }

    # ---------------- STRESS TEST 3: TRAIN VS UNSEEN (60% / 40% SPLIT) ----------------
    train_sharpes, unseen_sharpes = [], []
    train_rets, unseen_rets = [], []
    unseen_beats_bh = 0
    oos_per_market = {}
    for sym in symbols:
        m = market_data[sym]
        n_bars = len(m["bars"])
        s0 = warmups[sym]
        split_idx = max(s0 + 60, int(n_bars * TRAIN_FRAC))
        r_train = simulate_window(
            m["opens"], m["closes"], None,
            pre_signals[sym], FEE_BPS_BASELINE, s0, split_idx - 1,
            include_details=False,
        )
        r_unseen = simulate_window(
            m["opens"], m["closes"], None,
            pre_signals[sym], FEE_BPS_BASELINE, split_idx, n_bars - 1,
            include_details=False,
        )
        train_sharpes.append(r_train["sharpe"])
        unseen_sharpes.append(r_unseen["sharpe"])
        train_rets.append(r_train["total_return_pct"])
        unseen_rets.append(r_unseen["total_return_pct"])
        if r_unseen["beats_bh_sharpe"]:
            unseen_beats_bh += 1
        oos_per_market[sym] = {
            "train_return_pct": r_train["total_return_pct"],
            "train_sharpe": r_train["sharpe"],
            "unseen_return_pct": r_unseen["total_return_pct"],
            "unseen_bh_return_pct": r_unseen["bh_return_pct"],
            "unseen_sharpe": r_unseen["sharpe"],
            "unseen_bh_sharpe": r_unseen["bh_sharpe"],
            "split_date": m["dates"][split_idx],
        }

    mean_train_sharpe = float(np.mean(train_sharpes))
    mean_unseen_sharpe = float(np.mean(unseen_sharpes))
    mean_unseen_ret = float(np.mean(unseen_rets))
    oos_retention = (mean_unseen_sharpe / mean_train_sharpe) if mean_train_sharpe > 0 else 0.0

    test3_reasons = []
    if mean_unseen_ret <= 0.0 or mean_unseen_sharpe < 0.60:
        test3_reasons.append(
            f"Unseen OOS weak (return={mean_unseen_ret:.1f}%, Sharpe={mean_unseen_sharpe:.2f} < 0.60)"
        )
    if oos_retention < 0.50:
        test3_reasons.append(f"OOS/IS Sharpe retention {oos_retention:.2f} < 0.50")
    if unseen_beats_bh < 2:
        test3_reasons.append(f"Unseen beat B&H Sharpe on {unseen_beats_bh}/4 markets (need >=2)")
    test3_pass = len(test3_reasons) == 0
    oos_summary = {
        "train_mean_return_pct": round(float(np.mean(train_rets)), 2),
        "train_mean_sharpe": round(mean_train_sharpe, 3),
        "unseen_mean_return_pct": round(mean_unseen_ret, 2),
        "unseen_mean_sharpe": round(mean_unseen_sharpe, 3),
        "sharpe_retention": round(oos_retention, 3),
        "unseen_beats_bh_count": unseen_beats_bh,
        "per_market": oos_per_market,
        "passed": test3_pass,
    }

    # ---------------- STRESS TEST 4: RANDOM-ENTRY BASELINE AT SAME EXPOSURE ----------------
    rng = np.random.default_rng(mc_seed)
    pct_ranks = []
    beats_median_count = 0
    mc_per_market = {}
    for sym in symbols:
        m = market_data[sym]
        n_bars = len(m["bars"])
        s0 = warmups[sym]
        strat_sharpe = per_market[sym]["sharpe"]
        exp_frac = per_market[sym]["exposure_pct"] / 100.0
        avg_hold = per_market[sym].get("avg_hold_days", 10.0)

        rand_sharpes = []
        for _ in range(MC_TRIALS):
            rsig = _random_signals_same_exposure(n_bars, s0, n_bars - 1, exp_frac, avg_hold, rng)
            rr = simulate_window(
                m["opens"], m["closes"], None,
                rsig, FEE_BPS_BASELINE, s0, n_bars - 1,
                include_details=False,
            )
            rand_sharpes.append(rr["sharpe"])
        arr = np.array(rand_sharpes, dtype=float)
        pct_rank = float(np.mean(strat_sharpe > arr) * 100.0)
        p50 = float(np.percentile(arr, 50))
        p75 = float(np.percentile(arr, 75))
        p95 = float(np.percentile(arr, 95))
        pct_ranks.append(pct_rank)
        if strat_sharpe > p50:
            beats_median_count += 1
        mc_per_market[sym] = {
            "strategy_sharpe": strat_sharpe,
            "random_p50_sharpe": round(p50, 3),
            "random_p75_sharpe": round(p75, 3),
            "random_p95_sharpe": round(p95, 3),
            "percentile_rank": round(pct_rank, 1),
        }

    mean_pct_rank = float(np.mean(pct_ranks))
    test4_reasons = []
    if mean_pct_rank < 75.0:
        test4_reasons.append(f"Beat only {mean_pct_rank:.1f}% of same-exposure random entries (need >=75%)")
    if beats_median_count < 3:
        test4_reasons.append(f"Beat random median on {beats_median_count}/4 markets (need >=3)")
    test4_pass = len(test4_reasons) == 0
    random_summary = {
        "trials_per_market": MC_TRIALS,
        "mean_percentile_rank": round(mean_pct_rank, 1),
        "beats_median_count": beats_median_count,
        "per_market": mc_per_market,
        "passed": test4_pass,
    }

    # ---------------- DEFAULT-REJECT JUDGE ----------------
    all_reasons = precheck_reasons + test1_reasons + test2_reasons + test3_reasons + test4_reasons
    passed_all = (len(all_reasons) == 0)

    return {
        "id": idea["id"],
        "name": idea["name"],
        "family": family,
        "params": params,
        "origin": idea.get("origin", "template"),
        "verdict": "PASS" if passed_all else "FAIL",
        "death_reasons": all_reasons,
        "tests_passed_count": sum([test1_pass, test2_pass, test3_pass, test4_pass]) if not precheck_reasons else 0,
        "summary": {
            "mean_return_pct": round(mean_ret, 2),
            "mean_bh_return_pct": round(mean_bh_ret, 2),
            "mean_excess_return_pct": round(mean_excess, 2),
            "mean_cagr_pct": round(mean_cagr, 2),
            "mean_sharpe": round(mean_sharpe, 3),
            "mean_bh_sharpe": round(mean_bh_sharpe, 3),
            "mean_max_dd_pct": round(mean_dd, 2),
            "mean_trades": round(mean_trades, 1),
            "mean_exposure_pct": round(mean_exposure, 1),
            "mean_win_rate_pct": round(mean_win_rate, 1),
            "beats_bh_markets": sum(1 for s in symbols if per_market[s]["beats_bh_return"]),
        },
        "per_market": per_market,
        "stress_tests": {
            "precheck_passed": len(precheck_reasons) == 0,
            "precheck_reasons": precheck_reasons,
            "fee_sweep": {
                "passed": test1_pass,
                "reasons": test1_reasons,
                "tiers": fee_sweep,
                "sharpe_retention_10bps": round(sharpe_retention_10, 3),
            },
            "rolling_starts": {**rolling_summary, "reasons": test2_reasons},
            "train_vs_unseen": {**oos_summary, "reasons": test3_reasons},
            "random_baseline": {**random_summary, "reasons": test4_reasons},
        },
    }
