import os
import pandas as pd
import numpy as np
import yfinance as yf
from dotenv import load_dotenv
from alpaca.data.historical import OptionHistoricalDataClient
from alpaca.data.requests import OptionLatestQuoteRequest
import matplotlib.pyplot as plt

# --- LOAD ENV ---
load_dotenv()
api_key = os.getenv("ALPACA_API_KEY")
secret_key = os.getenv("ALPACA_API_SECRET") or os.getenv("ALPACA_SECRET_KEY")

# --- LOAD DATA ---
options_df = pd.read_csv("spy_options_3mo.csv")
unique_dates = options_df["query_date"].unique()[:3]  # First 3 unique dates
sample_df = options_df[options_df["query_date"].isin(unique_dates)].copy()

# --- FETCH QUOTES ---
client = OptionHistoricalDataClient(api_key, secret_key)
all_symbols = sample_df["symbol"].dropna().unique().tolist()

# Batch fetch quotes (Alpaca may limit batch size, so use chunks)
def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

quotes_dict = {}
for batch in chunks(all_symbols, 50):
    req = OptionLatestQuoteRequest(symbol_or_symbols=batch)
    quotes = client.get_option_latest_quote(req)
    quotes_dict.update(quotes)

# --- MERGE QUOTES INTO SAMPLE DF ---
sample_df["bid"] = sample_df["symbol"].map(lambda s: quotes_dict[s].bid_price if s in quotes_dict else np.nan)
sample_df["ask"] = sample_df["symbol"].map(lambda s: quotes_dict[s].ask_price if s in quotes_dict else np.nan)

# --- VIX DATA ---
start_date = pd.to_datetime(sample_df["query_date"].min())
end_date = pd.to_datetime(sample_df["query_date"].max())
vix = yf.download("^VIX", start=start_date, end=end_date)
vix_series = vix["Close"].reindex(pd.date_range(start_date, end_date, freq="B")).ffill()

# --- BACKTEST LOGIC (regime-based, simple P&L) ---
trade_log = []
VIX_LOW = 17
VIX_HIGH = 18

for day in pd.to_datetime(unique_dates):
    try:
        vix_today = float(vix_series.loc[day])
    except KeyError:
        continue
    regime = "NO_TRADE"
    if vix_today > VIX_HIGH:
        regime = "HIGH_VOL"
    elif vix_today < VIX_LOW:
        regime = "LOW_VOL"
    day_opts = sample_df[sample_df["query_date"] == day.strftime("%Y-%m-%d")]
    if day_opts.empty or regime == "NO_TRADE":
        continue
    # --- HIGH VOL: Iron Condor ---
    if regime == "HIGH_VOL":
        atm_strike = day_opts.loc[(day_opts["type"] == "call"), "strike"].sub(
            day_opts["strike"].mean()).abs().idxmin()
        atm_call = day_opts.loc[atm_strike]
        atm_put = day_opts.loc[(day_opts["type"] == "put") & (day_opts["strike"] == atm_call["strike"])]
        if not atm_put.empty:
            atm_put = atm_put.iloc[0]
        else:
            atm_put = None
        otm_call = day_opts[(day_opts["type"] == "call") & (day_opts["strike"] > atm_call["strike"] + 5)].sort_values("strike").head(1)
        otm_put = day_opts[(day_opts["type"] == "put") & (day_opts["strike"] < atm_call["strike"] - 5)].sort_values("strike", ascending=False).head(1)
        trade_log.append({
            "date": day,
            "regime": regime,
            "strategy": "IronCondor",
            "short_call_bid": atm_call["bid"] if atm_call is not None else np.nan,
            "short_put_bid": atm_put["bid"] if atm_put is not None else np.nan,
            "long_call_ask": otm_call["ask"].values[0] if not otm_call.empty else np.nan,
            "long_put_ask": otm_put["ask"].values[0] if not otm_put.empty else np.nan,
        })
    # --- LOW VOL: Diagonal ---
    elif regime == "LOW_VOL":
        atm_strike = day_opts.loc[(day_opts["type"] == "call"), "strike"].sub(
            day_opts["strike"].mean()).abs().idxmin()
        atm_call = day_opts.loc[atm_strike]
        trade_log.append({
            "date": day,
            "regime": regime,
            "strategy": "Diagonal",
            "long_call_ask": atm_call["ask"],
        })

# --- SIMPLE P&L ---
trade_log_df = pd.DataFrame(trade_log)
def calc_pnl(row):
    if row["strategy"] == "IronCondor":
        return (row["short_call_bid"] + row["short_put_bid"]) - (row["long_call_ask"] + row["long_put_ask"])
    elif row["strategy"] == "Diagonal":
        return -row["long_call_ask"]
    else:
        return 0
trade_log_df["pnl"] = trade_log_df.apply(calc_pnl, axis=1)
trade_log_df["cum_pnl"] = trade_log_df["pnl"].cumsum()

# --- PLOT ---
plt.figure(figsize=(10, 6))
plt.plot(trade_log_df["date"], trade_log_df["cum_pnl"], marker='o', label="Cumulative P&L")
plt.xlabel("Date")
plt.ylabel("Cumulative P&L ($)")
plt.title("Sample Options Backtest: Cumulative P&L (First 3 Days)")
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.show()

# --- SUMMARY ---
print(trade_log_df)
print(f"Total P&L: ${trade_log_df['pnl'].sum():.2f}")
print(f"Number of trades: {len(trade_log_df)}")
print(trade_log_df.groupby('strategy')["pnl"].sum())

# TODO: Scale up to all days, handle missing data, add more strategies, model expiry, etc. 