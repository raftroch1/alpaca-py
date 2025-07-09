import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta

# --- PARAMETERS ---
OPTIONS_CSV = "spy_options_3mo.csv"
TRADE_LOG_CSV = "options_regime_trades.csv"
VIX_LOW = 17
VIX_HIGH = 18

# --- LOAD DATA ---
options_df = pd.read_csv(OPTIONS_CSV, parse_dates=["query_date", "expiration", "last_quote_time"])
options_df["type"] = options_df["type"].str.lower()

start_date = options_df["query_date"].min()
end_date = options_df["query_date"].max()

# Download VIX data
vix = yf.download("^VIX", start=start_date, end=end_date)
vix_series = vix["Close"].reindex(pd.date_range(start_date, end_date, freq="B")).ffill()

# --- STRATEGY LOGIC ---
trade_log = []

for day in pd.date_range(start_date, end_date, freq="B"):
    try:
        vix_today = float(vix_series.loc[day])
    except KeyError:
        continue  # Skip if VIX data is missing for this day
    regime = "NO_TRADE"
    if vix_today > VIX_HIGH:
        regime = "HIGH_VOL"
    elif vix_today < VIX_LOW:
        regime = "LOW_VOL"
    # Filter options for this day and 0DTE
    day_opts = options_df[options_df["query_date"] == day]
    if day_opts.empty or regime == "NO_TRADE":
        continue
    # --- HIGH VOL: Sell Iron Condor & Iron Butterfly ---
    if regime == "HIGH_VOL":
        # Iron Condor: Sell ATM call/put, buy further OTM call/put
        atm_strike = day_opts.loc[(day_opts["type"] == "call"), "strike"].sub(
            day_opts["strike"].mean()).abs().idxmin()
        atm_call = day_opts.loc[atm_strike]
        atm_put = day_opts.loc[(day_opts["type"] == "put") & (day_opts["strike"] == atm_call["strike"])]
        if not atm_put.empty:
            atm_put = atm_put.iloc[0]
        else:
            atm_put = None
        # OTM call/put (5 strikes away)
        otm_call = day_opts[(day_opts["type"] == "call") & (day_opts["strike"] > atm_call["strike"] + 5)].sort_values("strike").head(1)
        otm_put = day_opts[(day_opts["type"] == "put") & (day_opts["strike"] < atm_call["strike"] - 5)].sort_values("strike", ascending=False).head(1)
        # Iron Condor trade log
        trade_log.append({
            "date": day,
            "regime": regime,
            "strategy": "IronCondor",
            "short_call": atm_call["symbol"] if atm_call is not None else None,
            "short_put": atm_put["symbol"] if atm_put is not None else None,
            "long_call": otm_call["symbol"].values[0] if not otm_call.empty else None,
            "long_put": otm_put["symbol"].values[0] if not otm_put.empty else None,
            "short_call_bid": atm_call["bid"] if atm_call is not None else None,
            "short_put_bid": atm_put["bid"] if atm_put is not None else None,
            "long_call_ask": otm_call["ask"].values[0] if not otm_call.empty else None,
            "long_put_ask": otm_put["ask"].values[0] if not otm_put.empty else None,
        })
        # Iron Butterfly: Sell ATM straddle, buy OTM wings
        # ATM call/put as above, OTM wings 10 strikes away
        otm_call_bfly = day_opts[(day_opts["type"] == "call") & (day_opts["strike"] > atm_call["strike"] + 10)].sort_values("strike").head(1)
        otm_put_bfly = day_opts[(day_opts["type"] == "put") & (day_opts["strike"] < atm_call["strike"] - 10)].sort_values("strike", ascending=False).head(1)
        trade_log.append({
            "date": day,
            "regime": regime,
            "strategy": "IronButterfly",
            "short_call": atm_call["symbol"] if atm_call is not None else None,
            "short_put": atm_put["symbol"] if atm_put is not None else None,
            "long_call": otm_call_bfly["symbol"].values[0] if not otm_call_bfly.empty else None,
            "long_put": otm_put_bfly["symbol"].values[0] if not otm_put_bfly.empty else None,
            "short_call_bid": atm_call["bid"] if atm_call is not None else None,
            "short_put_bid": atm_put["bid"] if atm_put is not None else None,
            "long_call_ask": otm_call_bfly["ask"].values[0] if not otm_call_bfly.empty else None,
            "long_put_ask": otm_put_bfly["ask"].values[0] if not otm_put_bfly.empty else None,
        })
    # --- LOW VOL: Buy Diagonal ---
    elif regime == "LOW_VOL":
        # Buy ATM call (as a simple proxy for diagonal)
        atm_strike = day_opts.loc[(day_opts["type"] == "call"), "strike"].sub(
            day_opts["strike"].mean()).abs().idxmin()
        atm_call = day_opts.loc[atm_strike]
        trade_log.append({
            "date": day,
            "regime": regime,
            "strategy": "Diagonal",
            "long_call": atm_call["symbol"],
            "long_call_ask": atm_call["ask"],
        })
    # TODO: Add P&L calculation, position management, multi-day holding, etc.
    # TODO: Add more strategies (credit spreads, straddles, etc.)

# --- SAVE & SUMMARY ---
trade_log_df = pd.DataFrame(trade_log)
trade_log_df.to_csv(TRADE_LOG_CSV, index=False)
print(f"Saved {len(trade_log_df)} trades to {TRADE_LOG_CSV}")
print(trade_log_df["strategy"].value_counts())
print(trade_log_df.head()) 