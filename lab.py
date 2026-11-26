#!/usr/bin/env python3
"""Backtest Lab runner:
1. Fetch real daily OHLC bars (fail-closed)
2. Update forward paper-trading tracking for existing survivors
3. Generate & evaluate new strategy ideas across 4 stress tests
4. Update journal (JSON + Markdown), survivors, and dashboard JSON
5. Commit & push to GitHub (unless --no-push is passed)
"""
import argparse
import datetime
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))

from backtester import FEE_BPS_BASELINE, evaluate_idea_on_universe, simulate_window  # noqa: E402
from fetch_data import UNIVERSE, fetch_all  # noqa: E402
from strategies import compute_strategy, generate_ideas  # noqa: E402

DATA_DIR = ROOT / "data"
DETAILS_DIR = DATA_DIR / "details"
JOURNAL_DIR = ROOT / "journal"
LJUBLJANA_TZ = ZoneInfo("Europe/Ljubljana")


def _clean_floats(arr) -> list[float | None]:
    out = []
    for x in arr:
        fx = float(x)
        out.append(round(fx, 4) if math.isfinite(fx) else None)
    return out


def _load_json(path: Path, default):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def _build_market_arrays(raw_bars: dict[str, list[dict]]) -> dict[str, dict]:
    market_data = {}
    for item in UNIVERSE:
        sym = item["symbol"]
        bars = raw_bars[sym]
        market_data[sym] = {
            "symbol": sym,
            "name": item["name"],
            "bars": bars,
            "dates": [b["date"] for b in bars],
            "opens": np.array([b["open"] for b in bars], dtype=float),
            "highs": np.array([b["high"] for b in bars], dtype=float),
            "lows": np.array([b["low"] for b in bars], dtype=float),
            "closes": np.array([b["close"] for b in bars], dtype=float),
        }
    return market_data


def _save_strategy_detail(idea: dict, market_data: dict, eval_result: dict):
    DETAILS_DIR.mkdir(parents=True, exist_ok=True)
    detail = {
        "id": idea["id"],
        "name": idea["name"],
        "family": idea["family"],
        "params": idea["params"],
        "markets": {},
    }
    for sym, m in market_data.items():
        comp = compute_strategy(m["bars"], idea["family"], idea["params"])
        pm = eval_result["per_market"][sym]
        ind = comp["indicators"]
        detail["markets"][sym] = {
            "warmup": int(comp["warmup"]),
            "start_idx": pm["start_idx"],
            "end_idx": pm["end_idx"],
            "equity_curve": pm["equity_curve"],
            "bh_curve": pm["bh_curve"],
            "trades": pm["trade_list"],
            "signals": [int(x) for x in comp["signals"]],
            "indicators": {
                "pane": ind["pane"],
                "label": ind.get("label", ""),
                "levels": ind.get("levels", []),
                "series": [
                    {
                        "name": s["name"],
                        "color": s["color"],
                        "values": _clean_floats(s["values"]),
                    }
                    for s in ind["series"]
                ],
            },
        }
    with open(DETAILS_DIR / f"{idea['id']}.json", "w", encoding="utf-8") as f:
        json.dump(detail, f, separators=(",", ":"))


def _strip_heavy_fields(eval_result: dict) -> dict:
    """Return compact summary record for journal.json & dashboard.json."""
    rec = {k: v for k, v in eval_result.items() if k != "per_market"}
    compact_pm = {}
    for sym, pm in eval_result["per_market"].items():
        compact_pm[sym] = {
            k: v
            for k, v in pm.items()
            if k not in ("equity_curve", "bh_curve", "trade_list")
        }
    rec["per_market"] = compact_pm
    return rec


def _update_survivors_forward(survivors: list[dict], market_data: dict) -> list[dict]:
    """Track forward paper-trading return on bars strictly after discovery date."""
    for surv in survivors:
        disc_date = surv["discovered_last_date"]
        fwd_pm = {}
        fwd_rets = []
        fwd_bh_rets = []
        for sym, m in market_data.items():
            dates = m["dates"]
            later_indices = [i for i, d in enumerate(dates) if d > disc_date]
            if len(later_indices) < 2:
                fwd_pm[sym] = {
                    "forward_bars": len(later_indices),
                    "forward_return_pct": 0.0,
                    "forward_bh_return_pct": 0.0,
                    "status": "Awaiting new bars after discovery",
                }
                continue
            comp = compute_strategy(m["bars"], surv["family"], surv["params"])
            s_idx = later_indices[0]
            e_idx = len(dates) - 1
            res = simulate_window(
                m["opens"], m["closes"], m["dates"],
                comp["signals"], FEE_BPS_BASELINE, s_idx, e_idx,
                include_details=False,
            )
            fwd_pm[sym] = {
                "forward_bars": e_idx - s_idx + 1,
                "forward_start_date": dates[s_idx],
                "forward_end_date": dates[e_idx],
                "forward_return_pct": res["total_return_pct"],
                "forward_bh_return_pct": res["bh_return_pct"],
                "trades": res["trades"],
                "status": "Active paper tracking",
            }
            fwd_rets.append(res["total_return_pct"])
            fwd_bh_rets.append(res["bh_return_pct"])
        surv["forward"] = {
            "updated_at": market_data["MSFT"]["dates"][-1],
            "mean_forward_return_pct": round(float(np.mean(fwd_rets)) if fwd_rets else 0.0, 2),
            "mean_forward_bh_return_pct": round(float(np.mean(fwd_bh_rets)) if fwd_bh_rets else 0.0, 2),
            "per_market": fwd_pm,
        }
    return survivors


def _write_journal_markdown(journal: list[dict], survivors: list[dict], run_info: dict):
    lines = [
        "# Backtest Lab Journal & Graveyard",
        "",
        f"- **Last Updated:** {run_info['run_at_ljubljana']} (`{run_info['run_at_utc']}`)",
        f"- **Total Ideas Evaluated:** {len(journal)}",
        f"- **Paper-Trading Survivors:** {len(survivors)}",
        f"- **Graveyard (Rejected):** {len(journal) - len(survivors)}",
        "",
        "> Paper only · In-sample and walk-forward backtest results · Not financial advice.",
        "",
        "## Paper-Trading Survivors",
        "",
    ]
    if not survivors:
        lines.append("_No strategies have survived all 4 stress tests yet. Most ideas die here, which is the point._")
    else:
        lines.append("| Strategy | Discovered | Mean Ret | B&H Ret | Mean Sharpe | OOS Sharpe | Forward Ret |")
        lines.append("|---|---|---:|---:|---:|---:|---:|")
        for s in survivors:
            fwd = s.get("forward", {}).get("mean_forward_return_pct", 0.0)
            lines.append(
                f"| {s['name']} | {s['discovered_at']} | {s['summary']['mean_return_pct']:.2f}% | "
                f"{s['summary']['mean_bh_return_pct']:.2f}% | {s['summary']['mean_sharpe']:.3f} | "
                f"{s['stress_tests']['train_vs_unseen']['unseen_mean_sharpe']:.3f} | {fwd:.2f}% |"
            )

    lines.extend(["", "## Evaluation Log (Newest First)", ""])
    lines.append("| Run | Idea | Verdict | Mean Ret | Mean Sharpe | Beat B&H | Reason / Notes |")
    lines.append("|---|---|---|---:|---:|---:|---|")
    for entry in reversed(journal):
        reasons = "; ".join(entry["death_reasons"]) if entry["death_reasons"] else "Passed all 4 stress tests"
        lines.append(
            f"| {entry['run_id']} | {entry['name']} | **{entry['verdict']}** | "
            f"{entry['summary']['mean_return_pct']:.2f}% | {entry['summary']['mean_sharpe']:.3f} | "
            f"{entry['summary']['beats_bh_markets']}/4 | {reasons} |"
        )
    with open(JOURNAL_DIR / "JOURNAL.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _git_commit_and_push(run_id: str, new_count: int, pass_count: int):
    cmds = [
        ["git", "add", "data", "journal"],
    ]
    for cmd in cmds:
        subprocess.run(cmd, cwd=ROOT, check=True)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True)
    if not status.stdout.strip():
        print("[git] No changes to commit.")
        return
    msg = f"lab: run {run_id} (+{new_count} ideas, {pass_count} survivors)"
    subprocess.run(["git", "commit", "-m", msg], cwd=ROOT, check=True)
    push_cmd = [
        "git", "-c", "credential.helper=!/usr/local/bin/gh auth git-credential",
        "push", "origin", "main",
    ]
    subprocess.run(push_cmd, cwd=ROOT, check=True)
    print(f"[git] Pushed: {msg}")


def run_lab(ideas_per_run: int | None = None, push: bool = True, seed: int | None = None):
    t0 = time.time()
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DETAILS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Fetch real market data (fail closed on error)
    bars_payload = fetch_all()
    market_data = _build_market_arrays(bars_payload["bars"])

    # 2. Load existing journal & survivors
    journal: list[dict] = _load_json(JOURNAL_DIR / "journal.json", [])
    survivors: list[dict] = _load_json(JOURNAL_DIR / "survivors.json", [])
    runs_history: list[dict] = _load_json(JOURNAL_DIR / "runs.json", [])

    existing_ids = {e["id"] for e in journal}
    is_first_pass = len(journal) == 0
    batch_size = ideas_per_run if ideas_per_run is not None else (26 if is_first_pass else 10)
    run_seed = seed if seed is not None else int(datetime.datetime.now().strftime("%Y%m%d%H"))

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_lj = now_utc.astimezone(LJUBLJANA_TZ)
    run_id = now_lj.strftime("%Y%m%d-%H%M")
    last_bar_date = max(m["dates"][-1] for m in market_data.values())

    # 3. Generate & evaluate new ideas
    new_ideas = generate_ideas(existing_ids, total_new=batch_size, seed=run_seed)
    new_records = []
    for idx, idea in enumerate(new_ideas):
        eval_res = evaluate_idea_on_universe(
            idea, market_data, compute_strategy, mc_seed=1000 + len(journal) + idx
        )
        _save_strategy_detail(idea, market_data, eval_res)
        compact = _strip_heavy_fields(eval_res)
        compact["run_id"] = run_id
        compact["evaluated_at_utc"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        compact["evaluated_at_ljubljana"] = now_lj.strftime("%Y-%m-%d %H:%M %Z")
        compact["data_last_date"] = last_bar_date
        journal.append(compact)
        new_records.append(compact)

        if compact["verdict"] == "PASS":
            surv_entry = {
                **compact,
                "discovered_at": now_lj.strftime("%Y-%m-%d %H:%M %Z"),
                "discovered_last_date": last_bar_date,
            }
            survivors.append(surv_entry)

        tag = "PASS" if compact["verdict"] == "PASS" else "DEAD"
        print(
            f"[eval {idx+1:2d}/{len(new_ideas)}] {tag} | {compact['name']:42s} | "
            f"Ret={compact['summary']['mean_return_pct']:7.2f}% | "
            f"Sharpe={compact['summary']['mean_sharpe']:5.3f} | "
            f"OOS={compact['stress_tests']['train_vs_unseen']['unseen_mean_sharpe']:5.3f} | "
            f"Tests={compact['tests_passed_count']}/4"
        )

    # 4. Update forward paper-trading metrics on all survivors
    survivors = _update_survivors_forward(survivors, market_data)

    elapsed_s = round(time.time() - t0, 2)
    run_info = {
        "run_id": run_id,
        "run_at_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_at_ljubljana": now_lj.strftime("%Y-%m-%d %H:%M %Z"),
        "new_ideas_tested": len(new_records),
        "new_survivors": sum(1 for r in new_records if r["verdict"] == "PASS"),
        "total_ideas": len(journal),
        "total_survivors": len(survivors),
        "elapsed_seconds": elapsed_s,
    }
    runs_history.append(run_info)

    # Save journal artifacts
    with open(JOURNAL_DIR / "journal.json", "w", encoding="utf-8") as f:
        json.dump(journal, f, indent=2)
    with open(JOURNAL_DIR / "survivors.json", "w", encoding="utf-8") as f:
        json.dump(survivors, f, indent=2)
    with open(JOURNAL_DIR / "runs.json", "w", encoding="utf-8") as f:
        json.dump(runs_history, f, indent=2)
    _write_journal_markdown(journal, survivors, run_info)

    # 5. Build Leaderboard & Dashboard JSON
    leaderboard = sorted(
        journal,
        key=lambda x: (
            1 if x["verdict"] == "PASS" else 0,
            x["tests_passed_count"],
            x["summary"]["mean_sharpe"],
            x["summary"]["mean_excess_return_pct"],
        ),
        reverse=True,
    )

    dashboard = {
        "meta": {
            "title": "BACKTEST-LAB // PAPER TERMINAL",
            "source": bars_payload["source"],
            "universe": [u["symbol"] for u in UNIVERSE],
            "universe_meta": bars_payload["meta"],
            "fee_bps_per_side": FEE_BPS_BASELINE,
            "execution_convention": "Signal at bar T close -> fill at bar T+1 open",
            "last_run": run_info,
        },
        "stats": {
            "total_ideas": len(journal),
            "survivors_count": len(survivors),
            "graveyard_count": len(journal) - len(survivors),
            "best_strategy": leaderboard[0]["name"] if leaderboard else None,
            "best_sharpe": leaderboard[0]["summary"]["mean_sharpe"] if leaderboard else None,
            "best_return_pct": leaderboard[0]["summary"]["mean_return_pct"] if leaderboard else None,
        },
        "leaderboard": leaderboard,
        "survivors": survivors,
        "journal": list(reversed(journal)),
        "runs": list(reversed(runs_history[-20:])),
    }
    with open(DATA_DIR / "dashboard.json", "w", encoding="utf-8") as f:
        json.dump(dashboard, f, separators=(",", ":"))

    print(
        f"\n[lab] Pass complete in {elapsed_s:.2f}s | Tested={len(new_records)} | "
        f"Total={len(journal)} | Survivors={len(survivors)}"
    )

    if push:
        _git_commit_and_push(run_id, len(new_records), len(survivors))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Backtest Lab daily pass")
    parser.add_argument("--ideas", type=int, default=None, help="Number of new ideas to evaluate")
    parser.add_argument("--no-push", action="store_true", help="Skip git commit and push")
    parser.add_argument("--seed", type=int, default=None, help="Deterministic RNG seed")
    args = parser.parse_args()
    try:
        run_lab(ideas_per_run=args.ideas, push=not args.no_push, seed=args.seed)
    except Exception as exc:
        print(f"ERROR: Lab run failed: {exc}", file=sys.stderr)
        sys.exit(1)
