import backtrader as bt
import pandas as pd
import os
from datetime import datetime

class EnhancedOptionsStrategy(bt.Strategy):
    params = (
        ('low_vol_threshold', 17),
        ('high_vol_threshold', 18),
        ('target_daily_return', 0.005),
        ('kelly_fraction', 0.5),
        ('max_trades_per_day', 2),
        ('log_dir', 'logs'),
    )

    def __init__(self):
        self.spy = self.datas[0]
        self.vix = self.datas[1]
        self.rsi = bt.indicators.RSI(self.spy.close, period=14)
        self.daily_start_value = None
        self.trades_today = 0
        self.logfile = self._init_logfile()
        self.pnl_log = []

    def _init_logfile(self):
        today = datetime.now().strftime('%Y-%m-%d')
        log_dir = os.path.join(self.p.log_dir, 'enhanced_options')
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, f'trades_{today}.csv')
        with open(log_path, 'w') as f:
            f.write('datetime,strategy,action,price,contracts,pnl\n')
        return log_path

    def log_trade(self, dt, strategy, action, price, contracts, pnl):
        with open(self.logfile, 'a') as f:
            f.write(f'{dt},{strategy},{action},{price},{contracts},{pnl}\n')

    def next(self):
        dt = self.datas[0].datetime.date(0)
        if self.daily_start_value is None:
            self.daily_start_value = self.broker.getvalue()
            self.trades_today = 0
        daily_pnl = self.broker.getvalue() - self.daily_start_value
        daily_return = daily_pnl / self.daily_start_value if self.daily_start_value else 0
        self.pnl_log.append((dt, daily_pnl))
        if daily_return >= self.p.target_daily_return:
            return
        if self.trades_today >= self.p.max_trades_per_day:
            return
        current_vix = self.vix[0]
        previous_vix = self.vix[-1] if len(self.vix) > 1 else current_vix
        momentum = self.rsi[0]
        # Regime logic (simplified for backtest)
        if current_vix > self.p.high_vol_threshold and current_vix > previous_vix:
            strategy = 'IRON_CONDOR'
        elif current_vix < self.p.low_vol_threshold and current_vix <= previous_vix:
            strategy = 'DIAGONAL'
        elif self.p.low_vol_threshold <= current_vix <= self.p.high_vol_threshold:
            if momentum > 70:
                strategy = 'PUT_CREDIT_SPREAD'
            elif momentum < 30:
                strategy = 'CALL_CREDIT_SPREAD'
            else:
                strategy = 'IRON_BUTTERFLY'
        else:
            strategy = 'NO_TRADE'
        if strategy == 'NO_TRADE':
            return
        # Position sizing (fractional Kelly, simplified)
        portfolio_value = self.broker.getvalue()
        max_risk = 5000  # placeholder, adjust per strategy
        contracts = int((portfolio_value * self.p.kelly_fraction) // max_risk)
        if contracts < 1:
            return
        # Simulate trade (buy/sell dummy option asset)
        if not self.position:
            self.buy(size=contracts)
            self.log_trade(dt, strategy, 'OPEN', self.spy.close[0], contracts, 0)
            self.trades_today += 1
        # Profit-taking/stop-loss logic (simplified)
        if self.position:
            entry_price = self.position.price
            pnl = (self.spy.close[0] - entry_price) * self.position.size
            if pnl > 0.5 * max_risk * contracts or pnl < -0.5 * max_risk * contracts:
                self.close()
                self.log_trade(dt, strategy, 'CLOSE', self.spy.close[0], contracts, pnl)

    def stop(self):
        # Save daily P&L log
        pnl_path = self.logfile.replace('trades_', 'pnl_')
        with open(pnl_path, 'w') as f:
            f.write('date,pnl\n')
            for dt, pnl in self.pnl_log:
                f.write(f'{dt},{pnl}\n')

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    # Load SPY and VIX data (CSV or DataFrame)
    spy_df = pd.read_csv('data/SPY.csv', index_col=0, parse_dates=True)
    vix_df = pd.read_csv('data/VIX.csv', index_col=0, parse_dates=True)
    spy_data = bt.feeds.PandasData(dataname=spy_df)
    vix_data = bt.feeds.PandasData(dataname=vix_df)
    cerebro.adddata(spy_data)
    cerebro.adddata(vix_data)
    cerebro.addstrategy(EnhancedOptionsStrategy)
    cerebro.broker.setcash(25000)
    cerebro.run()
    cerebro.plot() 