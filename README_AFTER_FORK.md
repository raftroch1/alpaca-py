
## Enhanced Multi-Regime Options Strategy

### Live Trading: `enhanced_multi_regime_options_strategy.py`
- Implements advanced regime-based options trading for SPY using Alpaca API.
- Features robust risk management (fractional Kelly, daily P&L targets, max trades/day).
- Supports Iron Condor, Iron Butterfly, Diagonal, Put/Call Credit Spreads.
- Uses VIX, RSI, and momentum for regime detection and strategy selection.
- Logs all trades and daily P&L to dated logs/ folders inside the strategy directory.
- Position management includes profit-taking and stop-loss logic.

### Backtesting: `backtrader_backtesting/enhanced_options_backtrader.py`
- Mirrors the enhanced live strategy logic using Backtrader.
- Loads historical SPY and VIX data (CSV format expected in `data/` folder).
- Simulates regime detection, position sizing, and risk management.
- Logs trades and daily P&L to logs/enhanced_options/.
- Requires `backtrader` and `pandas` (see `backtrader_backtesting/requirements.txt`).

#### Usage
1. For live trading, configure your API keys and run `enhanced_multi_regime_options_strategy.py`.
2. For backtesting, place historical SPY and VIX CSVs in `backtrader_backtesting/data/`, install requirements, and run the script.

--- 