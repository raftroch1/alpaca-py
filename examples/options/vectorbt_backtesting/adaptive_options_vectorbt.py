import vectorbt as vbt
import yfinance as yf
import pandas as pd
import numpy as np

# 1. Download SPY and VIX data for 2023
start = "2023-01-01"
end = "2023-12-31"
spy = yf.download("SPY", start=start, end=end)
vix = yf.download("^VIX", start=start, end=end)

# 2. Prepare data
spy_close = spy['Close']
vix_close = vix['Close']

# 3. Calculate regime logic (mimicking your strategy)
low_vol_threshold = 17
high_vol_threshold = 18
vix_prev = vix_close.shift(1)
regime = pd.Series("NO_TRADE", index=spy_close.index)
regime[(vix_close > vix_prev) & (vix_close > high_vol_threshold)] = "IRON_CONDOR"
regime[vix_close < low_vol_threshold] = "DIAGONAL"

# 4. Generate dummy signals based on regime
# For demo: DIAGONAL = long SPY, IRON_CONDOR = short SPY, NO_TRADE = flat
entries = (regime == "DIAGONAL")
short_entries = (regime == "IRON_CONDOR")
exits = entries.shift(1, fill_value=False) != entries  # exit when regime changes
short_exits = short_entries.shift(1, fill_value=False) != short_entries

# 5. Build vectorbt portfolio
portfolio = vbt.Portfolio.from_signals(
    spy_close,
    entries=entries,
    exits=exits,
    short_entries=short_entries,
    short_exits=short_exits,
    direction='both',
    freq='1D',
    init_cash=10000,
    fees=0.0
)

# 6. Output stats and plot
print(portfolio.stats())
portfolio.plot().show() 