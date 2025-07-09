import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

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
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), sharex=True, gridspec_kw={'height_ratios': [2, 1]})

# Per-trade P&L bar plot
colors = np.where(df["pnl"] >= 0, "#4caf50", "#f44336")  # green for win, red for loss
strategy_map = {s: i for i, s in enumerate(df["strategy"].unique())}
bar_positions = np.arange(len(df))

bars = ax1.bar(bar_positions, df["pnl"], color=colors, alpha=0.8, label="Per-Trade P&L")

# Add strategy markers above bars
for idx, row in df.iterrows():
    ax1.text(idx, row["pnl"] + np.sign(row["pnl"]) * max(abs(df["pnl"])) * 0.02, row["strategy"],
             ha='center', va='bottom' if row["pnl"] >= 0 else 'top', fontsize=8, color='black', rotation=90)

ax1.set_ylabel("P&L per Trade ($)")
ax1.set_title("Options Strategy Backtest: Per-Trade P&L")
ax1.grid(True, axis='y', linestyle='--', alpha=0.6)

# Cumulative P&L line plot
ax2.plot(bar_positions, df["cum_pnl"], marker='o', color='blue', label="Cumulative P&L")
ax2.set_ylabel("Cumulative P&L ($)")
ax2.set_xlabel("Trade Number (chronological)")
ax2.set_title("Cumulative P&L Over Time")
ax2.grid(True, axis='y', linestyle='--', alpha=0.6)

# X-ticks as dates (sparse for readability)
xtick_freq = max(1, len(df) // 15)
ax2.set_xticks(bar_positions[::xtick_freq])
ax2.set_xticklabels(df["date"].dt.strftime('%Y-%m-%d').iloc[::xtick_freq], rotation=45, ha='right')

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