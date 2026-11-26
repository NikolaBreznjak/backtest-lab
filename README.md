# Backtest Lab (Paper-Only Research Terminal)

Self-improving paper-only stock backtesting lab and trading-terminal dashboard.
Zero broker connections, zero real capital, not financial advice.

## Universe & Data
- **Markets:** `MSFT`, `AAPL`, `NVDA`, `^GSPC` (S&P 500)
- **Source:** Yahoo Finance v8 Chart API (`5y`, `1d` OHLCV bars). Fails closed if any fetch fails or returns insufficient bars; prices are never invented.
- **Rules:** Defined in [`LAB_RULES.md`](LAB_RULES.md).

## Single Execution Convention
- Signals are evaluated strictly at bar `T` close (zero look-ahead).
- Positions execute at bar `T+1` open.
- Baseline transaction fee: **2 bps (0.02%) per side** on every entry and exit.

## Daily Run Command
```bash
python3 lab.py
```
This fetches fresh daily bars, updates forward paper tracking on existing survivors, proposes and evaluates new strategy ideas across all 4 stress tests, rebuilds the journal (`journal/JOURNAL.md`, `journal/journal.json`) and dashboard JSON (`data/dashboard.json`), and commits & pushes to `main`.

To run locally without pushing:
```bash
python3 lab.py --no-push
```
