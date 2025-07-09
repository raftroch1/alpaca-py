# Project Tasks

## Completed
- [x] Repo cleanup, submodule and branch sync
- [x] Logging and CSV output to dated logs/ folders
- [x] README and documentation improvements
- [x] Implemented enhanced_multi_regime_options_strategy.py (live trading)
- [x] Implemented enhanced_options_backtrader.py (Backtrader backtest)
- [x] Added requirements.txt for backtesting

## In Progress / Next Steps
- [ ] Parameterize additional regime/strategy selection indicators (see below)
- [ ] Add more advanced analytics and reporting
- [ ] Further optimize position sizing and risk management
- [ ] Integrate with additional data sources if needed

## Additional Regime/Strategy Selection Parameters (beyond VIX)
- RSI (Relative Strength Index)
- Multi-timeframe momentum (e.g., 1h, 4h, daily)
- SPY realized volatility (historical stddev)
- Put/Call ratio
- Skew (difference between IV of OTM puts/calls)
- Term structure (VIX vs VXST, VIX9D, etc.)
- Market breadth (advancers/decliners, volume)
- Macro events (FOMC, CPI, etc.) 