# Backtest Lab Rules (Paper-Only Research Protocol)

> **Written before data ingestion and strategy evaluation.**  
> Paper-only backtest & research lab. Zero broker connections, zero real capital, not financial advice.

## 1. Universe & Data Integrity
- **Markets (4):** `MSFT` (Microsoft), `AAPL` (Apple), `NVDA` (NVIDIA), `^GSPC` (S&P 500 Index).
- **Timeframe:** Daily (`1d`) OHLC bars, targeting **5 years** (~1,250 trading days) so both in-sample training and out-of-sample unseen holdout cover multiple market regimes (including 2022 drawdown and 2023–2026 rally).
- **Source:** Free Yahoo Finance Chart API (`v8/finance/chart/{symbol}?range=5y&interval=1d`).
- **Strict No-Fabrication Rule:** Never invent, interpolate, or forward-fill missing OHLC prices. Any incomplete bar (e.g., an active intraday/unsettled bar with `null` Open/High/Low/Close) is dropped. If a symbol fetch fails or returns fewer than 500 valid daily bars, the entire run aborts with a non-zero exit code.

## 2. Single Execution & Fee Convention
- **Position Model:** Long-only (`0%` flat or `100%` invested in the asset). No leverage, no margin, no shorting.
- **Strictly Causal Signals (Zero Look-Ahead):**
  - Indicator values and trade signals at bar `t` are computed strictly from bars `0..t`.
  - A signal decided at the **close of bar `t`** is executed at the **open of bar `t + 1`**.
- **Transaction Costs (Baseline):**
  - **2 bps (0.02% / `0.0002`) per side** applied to every entry and every exit:
    - Entry fill price: `open[t+1] * (1 + fee_rate)`
    - Exit fill price: `open[t+1] * (1 - fee_rate)`
- **Benchmark:** Buy & Hold on the exact same market over the exact same evaluation window `[eval_start .. eval_end]`, entering at `open[eval_start]` with `2 bps` entry fee and marked to `close[eval_end]` (with `2 bps` exit fee in terminal comparison).

## 3. Activity & Realism Constraints (Pre-Checks)
To prevent degenerate "buy once and hold" or hyper-fitting micro-trades:
- **Minimum Trades:** Mean closed round-trip trades across the 4 markets `>= 10` (and `>= 6` on each individual market).
- **Exposure Bounds:** Mean time-in-market exposure between `10%` and `92%` (strategies that stay `> 92%` invested are just disguised Buy & Hold).

## 4. The Four Stress Tests (Reject by Default)
A strategy idea is **REJECTED (sent to the graveyard)** unless it passes **all four** stress tests simultaneously.

### Test 1 — Fee Sweep (`2, 5, 10, 20 bps` per side)
- Re-run the exact strategy across all 4 markets at `2`, `5`, `10`, and `20 bps` per side.
- **Pass Thresholds:**
  1. At baseline `2 bps`, beat Buy & Hold after fees (either higher Sharpe OR higher total return) on at least **2 of 4** markets.
  2. At `10 bps` per side, universe-average CAGR `> 0%` AND universe-average Sharpe `>= 0.50` (and retains at least `65%` of its `2 bps` Sharpe).
  3. At `20 bps` per side, universe-average total return `> 0%`.

### Test 2 — Every Start Date (Rolling Starts)
- Evaluate rolling start dates spaced every **21 trading days** (~monthly) across the full history, requiring at least **252 trading days** (~1 year) remaining in each window.
- **Pass Thresholds:**
  1. Across all `(market, start_date)` windows, **>= 65%** finish with positive total return.
  2. Across all `(market, start_date)` windows, **>= 50%** beat Buy & Hold Sharpe over that exact same window.

### Test 3 — Train vs Unseen (Out-of-Sample Holdout)
- Chronological split:
  - **Train (In-Sample):** First **60%** of bars (~3 years).
  - **Unseen (Out-of-Sample):** Last **40%** of bars (~2 years).
- **Pass Thresholds:**
  1. On the **Unseen** holdout, universe-average total return `> 0%` and universe-average Sharpe `>= 0.60`.
  2. **OOS / IS Sharpe Retention** (`unseen_sharpe / train_sharpe`) `>= 0.50` (prevents curve-fit collapse).
  3. Beats Buy & Hold Sharpe on at least **2 of 4** markets during the **Unseen** holdout.

### Test 4 — Random-Entry Baseline (Same Exposure Monte Carlo)
- For each market, measure the strategy's exact exposure fraction `p` and average trade holding duration `L`.
- Run **200 Monte Carlo random-entry trials** per market matching exposure `p` and holding duration `L` at `2 bps` fees.
- **Pass Thresholds:**
  1. Strategy beats the **75th percentile** (top quartile) of random-entry Sharpe on average across the 4 markets (mean percentile rank `>= 75%`).
  2. Strategy beats the **50th percentile** (median) of random-entry Sharpe on at least **3 of 4** markets.

## 5. Journal, Graveyard & Paper-Trading Survivors
- Every evaluated idea is permanently appended to `journal/journal.json` and `journal/JOURNAL.md` with its parameters, full metrics, stress-test breakdown, verdict (`PASS` or `FAIL`), and exact failure reasons if rejected.
- Ideas that pass all 4 tests enter `journal/survivors.json` (the Paper-Trading Survivors list).
- On every subsequent daily run, existing survivors are re-evaluated on newly arrived bars to track **forward paper-trading return** since their discovery date (`forward_start_date`), without re-tuning any parameters.
