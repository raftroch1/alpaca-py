import backtrader as bt
import yfinance as yf
from datetime import datetime, timedelta
import pandas as pd

class AdaptiveOptionsStrategy(bt.Strategy):
    params = (
        ('low_vol_threshold', 17),
        ('high_vol_threshold', 18),
    )

    def __init__(self):
        self.vix = self.datas[1]  # VIX data feed
        self.spy = self.datas[0]  # SPY data feed
        self.order = None

    def next(self):
        vix_now = self.vix.close[0]
        vix_prev = self.vix.close[-1]
        regime = "NO_TRADE"
        if vix_now > vix_prev and vix_now > self.params.high_vol_threshold:
            regime = "IRON_CONDOR"
        elif vix_now < self.params.low_vol_threshold:
            regime = "DIAGONAL"

        # Long SPY for DIAGONAL, Short SPY for IRON_CONDOR, Flat for NO_TRADE
        if regime == "DIAGONAL" and not self.position:
            self.order = self.buy(size=10)
        elif regime == "IRON_CONDOR" and not self.position:
            self.order = self.sell(size=10)
        elif regime == "NO_TRADE" and self.position:
            self.close()

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    # Download 3 months of data
    end = datetime.today()
    start = end - timedelta(days=90)
    spy_df = yf.download('SPY', start=start, end=end)
    vix_df = yf.download('^VIX', start=start, end=end)

    # Flatten columns if MultiIndex (use OHLCV field names)
    if isinstance(spy_df.columns, pd.MultiIndex):
        spy_df.columns = spy_df.columns.get_level_values(0)
    if isinstance(vix_df.columns, pd.MultiIndex):
        vix_df.columns = vix_df.columns.get_level_values(0)

    # Print columns and shape for debugging
    print("SPY columns after flattening:", spy_df.columns)
    print("VIX columns after flattening:", vix_df.columns)
    print("SPY shape:", spy_df.shape)
    print("VIX shape:", vix_df.shape)

    # Forward-fill and drop any remaining NaNs
    spy_df = spy_df.ffill().dropna()
    vix_df = vix_df.ffill().dropna()

    # Align indices to ensure both have the same dates
    common_idx = spy_df.index.intersection(vix_df.index)
    spy_df = spy_df.loc[common_idx]
    vix_df = vix_df.loc[common_idx]

    # Check for empty DataFrames
    if spy_df.empty or vix_df.empty:
        raise ValueError("SPY or VIX DataFrame is empty after cleaning. Check your data download and cleaning steps.")

    # Ensure all required columns are present and non-NaN
    required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
    for df in [spy_df, vix_df]:
        if not all(col in df.columns for col in required_cols):
            # Try to auto-rename columns like 'SPY_Open' to 'Open'
            df.columns = [col.split('_')[-1] for col in df.columns]
    for col in required_cols:
        if col not in spy_df.columns:
            spy_df[col] = spy_df['Close'] if col != 'Volume' else 0
        if col not in vix_df.columns:
            vix_df[col] = vix_df['Close'] if col != 'Volume' else 0
    spy_df = spy_df[required_cols]
    vix_df = vix_df[required_cols]
    spy_df = spy_df.ffill().bfill().fillna(0)
    vix_df = vix_df.ffill().bfill().fillna(0)

    # Add SPY data
    data0 = bt.feeds.PandasData(dataname=spy_df)
    cerebro.adddata(data0, name='SPY')
    # Add VIX data
    data1 = bt.feeds.PandasData(dataname=vix_df)
    cerebro.adddata(data1, name='VIX')

    cerebro.addstrategy(AdaptiveOptionsStrategy)
    cerebro.broker.set_cash(10000)
    print('Starting Portfolio Value: %.2f' % cerebro.broker.getvalue())
    cerebro.run()
    print('Final Portfolio Value: %.2f' % cerebro.broker.getvalue())
    cerebro.plot() 