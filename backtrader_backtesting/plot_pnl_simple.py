import pandas as pd
import matplotlib.pyplot as plt

TRADES_CSV = "options_regime_trades.csv"

# --- LOAD TRADES ---
df = pd.read_csv(TRADES_CSV, parse_dates=["date"])

# --- SIMPLE P&L CALCULATION ---
def calc_pnl(row):
    if row["strategy"] in ["IronCondor", "IronButterfly"]:
        # Sell to open, assume expires worthless (max profit)
        short_call = row["short_call_bid"] if pd.notnull(row["short_call_bid"]) else 0
        short_put = row["short_put_bid"] if pd.notnull(row["short_put_bid"]) else 0
        long_call = row["long_call_ask"] if pd.notnull(row["long_call_ask"]) else 0
        long_put = row["long_put_ask"] if pd.notnull(row["long_put_ask"]) else 0
        return (short_call + short_put) - (long_call + long_put)
    elif row["strategy"] == "Diagonal":
        # Buy to open, assume expires worthless (max loss)
        long_call = row["long_call_ask"] if pd.notnull(row["long_call_ask"]) else 0
        return -long_call
    else:
        return 0

df["pnl"] = df.apply(calc_pnl, axis=1)

df["cum_pnl"] = df["pnl"].cumsum()

# --- PLOT ---
plt.figure(figsize=(10, 6))
plt.plot(df["date"], df["cum_pnl"], label="Cumulative P&L")
plt.xlabel("Date")
plt.ylabel("Cumulative P&L ($)")
plt.title("Simple Options Strategy Backtest: Cumulative P&L")
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.show()

# --- SUMMARY ---
print(f"Total P&L: ${df['pnl'].sum():.2f}")
print(f"Number of trades: {len(df)}")
print(f"Winning trades: {(df['pnl'] > 0).sum()}")
print(f"Losing trades: {(df['pnl'] < 0).sum()}")
print(df.groupby('strategy')["pnl"].sum())

# TODO: Use actual expiry value based on SPY price for more realism
# TODO: Model multi-day holding, slippage, commissions, etc. 