import os
try:
    import backtrader as bt
    import yfinance as yf
    import pandas as pd
except ImportError as e:
    print(f"Missing package: {e.name}. Please install it with 'pip install {e.name}' and try again.")
    exit(1)

from datetime import datetime, timedelta
import csv

class MultiRegimeBacktestStrategy(bt.Strategy):
    params = (
        ('low_vol_threshold', 17),
        ('high_vol_threshold', 18),
    )

    def __init__(self):
        self.vix = self.datas[1]  # VIX data feed
        self.spy = self.datas[0]  # SPY data feed
        self.order = None
        self.regime_log = []
        self.last_regime = None
        self.csv_file = 'trade_pnl_log.csv'
        # Write header if file does not exist
        if not os.path.exists(self.csv_file):
            with open(self.csv_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['date', 'gross_pnl', 'net_pnl', 'regime'])

    def next(self):
        vix_now = self.vix.close[0]
        vix_prev = self.vix.close[-1]
        regime = "NO_TRADE"
        if vix_now > vix_prev and vix_now > self.params.high_vol_threshold:
            regime = "IRON_CONDOR"
        elif vix_now < self.params.low_vol_threshold:
            regime = "DIAGONAL"
        elif self.params.low_vol_threshold <= vix_now <= self.params.high_vol_threshold:
            regime = "MODERATE"  # Would be PUT_CREDIT_SPREAD, CALL_CREDIT_SPREAD, or IRON_BUTTERFLY
        self.regime_log.append((self.datas[0].datetime.date(0), regime))
        self.last_regime = regime
        # For backtest: Long SPY for DIAGONAL, Short SPY for IRON_CONDOR, Flat for NO_TRADE/MODERATE
        if regime == "DIAGONAL" and not self.position:
            self.order = self.buy(size=10)
        elif regime == "IRON_CONDOR" and not self.position:
            self.order = self.sell(size=10)
        elif regime in ["NO_TRADE", "MODERATE"] and self.position:
            self.close()

    def notify_trade(self, trade):
        if trade.isclosed:
            trade_date = self.datas[0].datetime.date(0)
            gross_pnl = trade.pnl
            net_pnl = trade.pnlcomm
            regime = self.last_regime if self.last_regime else ''
            print(f"{trade_date}: Trade closed. Gross P&L: {gross_pnl:.2f}, Net P&L: {net_pnl:.2f}")
            with open(self.csv_file, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([trade_date, gross_pnl, net_pnl, regime])

    def stop(self):
        print("\nRegime log (date, regime):")
        for date, regime in self.regime_log:
            print(date, regime)

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    # Download 1 year of data
    end = datetime.today()
    start = end - timedelta(days=365)
    spy_df = yf.download('SPY', start=start, end=end)
    vix_df = yf.download('^VIX', start=start, end=end)

    # Flatten columns if MultiIndex (use OHLCV field names)
    if isinstance(spy_df.columns, pd.MultiIndex):
        spy_df.columns = spy_df.columns.get_level_values(0)
    if isinstance(vix_df.columns, pd.MultiIndex):
        vix_df.columns = vix_df.columns.get_level_values(0)

    # Forward-fill and drop any remaining NaNs
    spy_df = spy_df.ffill().dropna()
    vix_df = vix_df.ffill().dropna()

    # Align indices to ensure both have the same dates
    common_idx = spy_df.index.intersection(vix_df.index)
    spy_df = spy_df.loc[common_idx]
    vix_df = vix_df.loc[common_idx]

    # Ensure all required columns are present and non-NaN
    required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
    for df in [spy_df, vix_df]:
        if not all(col in df.columns for col in required_cols):
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

    cerebro.addstrategy(MultiRegimeBacktestStrategy)
    cerebro.broker.set_cash(25000)
    print('Starting Portfolio Value: %.2f' % cerebro.broker.getvalue())
    cerebro.run()
    print('Final Portfolio Value: %.2f' % cerebro.broker.getvalue())
    cerebro.plot() 