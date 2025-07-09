<<<<<<< HEAD
import asyncio
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient, OptionHistoricalDataClient
from alpaca.data.live import StockDataStream, OptionDataStream
from alpaca.data.requests import StockBarsRequest, OptionBarsRequest, OptionLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.requests import GetOptionContractsRequest, MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from datetime import datetime, timedelta, time as dtime
import pandas as pd
import numpy as np
import os
from dotenv import load_dotenv
import yfinance as yf

# Robustly find and load .env from the project root (where .env.example is)
def find_project_root_with_env(start_path):
    current = os.path.abspath(start_path)
    while not os.path.exists(os.path.join(current, '.env')) and current != os.path.dirname(current):
        current = os.path.dirname(current)
    return current

project_root = find_project_root_with_env(__file__)
dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=dotenv_path)

class AdaptiveOptionsStrategy:
    def __init__(self, api_key, secret_key, paper=True):
        self.trading_client = TradingClient(api_key, secret_key, paper=paper)
        self.stock_data_client = StockHistoricalDataClient(api_key, secret_key)
        self.option_data_client = OptionHistoricalDataClient(api_key, secret_key)
        # Strategy parameters
        self.vix_threshold = 0  # VIX > previous day
        self.low_vol_threshold = 17  # VIX below this for diagonal
        self.high_vol_threshold = 18  # VIX above this for iron condor
        # Position sizing
        self.max_risk_per_trade = 0.02  # 2% of portfolio per trade
        self.iron_condor_target_profit = 0.25  # 25% profit target
    async def get_current_vix(self):
        try:
            vix = yf.Ticker("^VIX")
            hist = vix.history(period="5d")
            if len(hist) >= 2:
                current_vix = hist['Close'].iloc[-1]
                previous_vix = hist['Close'].iloc[-2]
                return current_vix, previous_vix
            else:
                print("VIX history data is too short or missing:", hist)
                return None, None
        except Exception as e:
            import traceback
            print(f"Error getting VIX data from Yahoo Finance: {e}")
            traceback.print_exc()
            return None, None
    async def get_spy_price(self):
        try:
            bars_request = StockBarsRequest(
                symbol_or_symbols=["SPY"],
                timeframe=TimeFrame.Minute,
                start=datetime.now() - timedelta(minutes=5),
                end=datetime.now()
            )
            bars = self.stock_data_client.get_stock_bars(bars_request)
            return bars.df['close'].iloc[-1]
        except Exception as e:
            print(f"Error getting SPY price: {e}")
            return None
    async def analyze_market_conditions(self):
        current_vix, previous_vix = await self.get_current_vix()
        if current_vix is None or previous_vix is None:
            return "NO_TRADE", "Unable to get VIX data"
        conditions = {
            'current_vix': current_vix,
            'previous_vix': previous_vix,
            'vix_higher': current_vix > previous_vix,
            'low_volatility': current_vix < self.low_vol_threshold,
            'high_volatility': current_vix > self.high_vol_threshold
        }
        if conditions['vix_higher'] and conditions['high_volatility']:
            return "IRON_CONDOR", conditions
        elif conditions['low_volatility']:
            return "DIAGONAL", conditions
        else:
            return "NO_TRADE", conditions
    async def get_option_quotes(self, symbol_list):
        try:
            quote_request = OptionLatestQuoteRequest(symbol_or_symbols=symbol_list)
            quotes = self.option_data_client.get_option_latest_quote(quote_request)
            return quotes
        except Exception as e:
            print(f"Error getting option quotes: {e}")
            return None
    async def find_target_delta_options(self, spy_price, target_delta=20, dte=0):
        try:
            if dte == 0:
                expiry = datetime.now().date()
            else:
                expiry = datetime.now().date() + timedelta(days=dte)
            contracts_request = GetOptionContractsRequest(
                underlying_symbol="SPY",
                expiration_date=expiry,
                page_size=1000
            )
            contracts = self.trading_client.get_option_contracts(contracts_request)
            target_call_strike = spy_price * (1 + target_delta/100 * 0.1)
            target_put_strike = spy_price * (1 - target_delta/100 * 0.1)
            call_options = []
            put_options = []
            for contract in contracts:
                if contract.type == "call":
                    if abs(contract.strike_price - target_call_strike) < 10:
                        call_options.append(contract)
                elif contract.type == "put":
                    if abs(contract.strike_price - target_put_strike) < 10:
                        put_options.append(contract)
            call_options.sort(key=lambda x: abs(x.strike_price - target_call_strike))
            put_options.sort(key=lambda x: abs(x.strike_price - target_put_strike))
            return call_options[:5], put_options[:5]
        except Exception as e:
            print(f"Error finding target delta options: {e}")
            return [], []
    def calculate_position_size(self, portfolio_value, strategy_type):
        max_risk_amount = portfolio_value * self.max_risk_per_trade
        if strategy_type == "IRON_CONDOR":
            estimated_max_risk = 700
            contracts = int(max_risk_amount / estimated_max_risk)
        elif strategy_type == "DIAGONAL":
            estimated_max_risk = 150
            contracts = int(max_risk_amount / estimated_max_risk)
        return max(1, min(contracts, 20))
    async def execute_iron_condor(self, spy_price, contracts):
        try:
            call_options, put_options = await self.find_target_delta_options(
                spy_price, target_delta=20, dte=0
            )
            if not call_options or not put_options:
                return False, "Could not find suitable option contracts"
            short_call = call_options[0]
            short_put = put_options[0]
            long_call_strike = short_call.strike_price + 5
            long_put_strike = short_put.strike_price - 5
            long_call = None
            long_put = None
            for contract in call_options:
                if contract.strike_price == long_call_strike:
                    long_call = contract
                    break
            for contract in put_options:
                if contract.strike_price == long_put_strike:
                    long_put = contract
                    break
            if not long_call or not long_put:
                return False, "Could not find long option contracts"
            symbols = [short_call.symbol, long_call.symbol, short_put.symbol, long_put.symbol]
            quotes = await self.get_option_quotes(symbols)
            if not quotes:
                return False, "Could not get option quotes"
            credit = (quotes[short_call.symbol].bid_price + quotes[short_put.symbol].bid_price - 
                     quotes[long_call.symbol].ask_price - quotes[long_put.symbol].ask_price)
            print(f"Iron Condor Setup ({contracts} contracts):")
            print(f"Short Call: {short_call.strike_price} @ ${quotes[short_call.symbol].bid_price}")
            print(f"Long Call:  {long_call.strike_price} @ ${quotes[long_call.symbol].ask_price}")
            print(f"Short Put:  {short_put.strike_price} @ ${quotes[short_put.symbol].bid_price}")
            print(f"Long Put:   {long_put.strike_price} @ ${quotes[long_put.symbol].ask_price}")
            print(f"Expected Credit: ${credit * 100:.2f} per spread")
            orders = [
                self.create_option_order(short_call.symbol, OrderSide.SELL, contracts, quotes[short_call.symbol].bid_price),
                self.create_option_order(long_call.symbol, OrderSide.BUY, contracts, quotes[long_call.symbol].ask_price),
                self.create_option_order(short_put.symbol, OrderSide.SELL, contracts, quotes[short_put.symbol].bid_price),
                self.create_option_order(long_put.symbol, OrderSide.BUY, contracts, quotes[long_put.symbol].ask_price)
            ]
            for order in orders:
                try:
                    response = self.trading_client.submit_order(order)
                    print(f"Order submitted: {response.id}")
                except Exception as e:
                    print(f"Error submitting order: {e}")
                    return False, f"Order execution failed: {e}"
            return True, f"Iron condor executed: ${credit * 100 * contracts:.2f} credit"
        except Exception as e:
            return False, f"Error executing iron condor: {e}"
    async def execute_diagonal(self, spy_price, contracts):
        try:
            dte0_calls, _ = await self.find_target_delta_options(spy_price, target_delta=40, dte=0)
            dte7_calls, _ = await self.find_target_delta_options(spy_price, target_delta=40, dte=7)
            if not dte0_calls or not dte7_calls:
                return False, "Could not find suitable option contracts"
            target_strike = None
            long_call = None
            short_call = None
            for long_contract in dte7_calls:
                for short_contract in dte0_calls:
                    if abs(long_contract.strike_price - short_contract.strike_price) < 0.5:
                        target_strike = long_contract.strike_price
                        long_call = long_contract
                        short_call = short_contract
                        break
                if target_strike:
                    break
            if not long_call or not short_call:
                return False, "Could not find matching strike options"
            quotes = await self.get_option_quotes([long_call.symbol, short_call.symbol])
            if not quotes:
                return False, "Could not get option quotes"
            net_debit = (quotes[long_call.symbol].ask_price - quotes[short_call.symbol].bid_price)
            print(f"Diagonal Spread Setup ({contracts} contracts):")
            print(f"Long Call (7DTE):  {target_strike} @ ${quotes[long_call.symbol].ask_price}")
            print(f"Short Call (0DTE): {target_strike} @ ${quotes[short_call.symbol].bid_price}")
            print(f"Net Debit: ${net_debit * 100:.2f} per spread")
            orders = [
                self.create_option_order(long_call.symbol, OrderSide.BUY, contracts, quotes[long_call.symbol].ask_price),
                self.create_option_order(short_call.symbol, OrderSide.SELL, contracts, quotes[short_call.symbol].bid_price)
            ]
            for order in orders:
                try:
                    response = self.trading_client.submit_order(order)
                    print(f"Order submitted: {response.id}")
                except Exception as e:
                    print(f"Error submitting order: {e}")
                    return False, f"Order execution failed: {e}"
            return True, f"Diagonal spread executed: ${net_debit * 100 * contracts:.2f} debit"
        except Exception as e:
            return False, f"Error executing diagonal: {e}"
    def create_option_order(self, symbol, side, quantity, limit_price):
        return LimitOrderRequest(
            symbol=symbol,
            qty=quantity,
            side=side,
            time_in_force=TimeInForce.DAY,
            limit_price=round(limit_price, 2)
        )
    async def check_exit_conditions(self):
        current_time = datetime.now().time()
        target_time = datetime.strptime("11:30", "%H:%M").time()
        if current_time >= target_time:
            return True, "Target time reached"
        return False, "No exit conditions met"
    async def run_strategy(self):
        print("Starting adaptive options strategy...")
        account = self.trading_client.get_account()
        portfolio_value = float(account.portfolio_value)
        print(f"Portfolio value: ${portfolio_value:,.2f}")
        strategy, conditions = await self.analyze_market_conditions()
        print(f"Market analysis: {strategy}")
        print(f"Conditions: {conditions}")
        if strategy == "NO_TRADE":
            print("No trading conditions met today")
            return
        spy_price = await self.get_spy_price()
        if not spy_price:
            print("Could not get SPY price")
            return
        contracts = self.calculate_position_size(portfolio_value, strategy)
        print(f"Position size: {contracts} contracts")
        if strategy == "IRON_CONDOR":
            success, message = await self.execute_iron_condor(spy_price, contracts)
        elif strategy == "DIAGONAL":
            success, message = await self.execute_diagonal(spy_price, contracts)
        print(f"Execution result: {success} - {message}")
        if success:
            await self.monitor_positions()
    async def monitor_positions(self):
        print("Monitoring positions...")
        while True:
            should_exit, reason = await self.check_exit_conditions()
            if should_exit:
                print(f"Exit condition met: {reason}")
                break
            await asyncio.sleep(300)

# Usage example
async def main():
    strategy = AdaptiveOptionsStrategy(
        api_key=os.getenv("ALPACA_API_KEY"),
        secret_key=os.getenv("ALPACA_SECRET_KEY"),
        paper=True
    )
    def is_market_open():
        now = datetime.now().time()
        return dtime(9, 30) <= now <= dtime(16, 0)
    while True:
        if not is_market_open():
            print("Market is closed. Sleeping for 10 minutes...")
            await asyncio.sleep(600)
            continue
        await strategy.run_strategy()
        print("Sleeping for 5 minutes before next check...")
        await asyncio.sleep(300)

if __name__ == "__main__":
    asyncio.run(main()) 
=======
import os
from datetime import datetime

# Ensure logs directory exists
logs_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(logs_dir, exist_ok=True)

# Helper for timestamped log/csv filenames
now_str = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
log_path = os.path.join(logs_dir, f"adaptive_{now_str}.log")
csv_path = os.path.join(logs_dir, f"adaptive_{now_str}.csv")

# Wherever you write logs or CSVs, use log_path/csv_path instead of a root-level file
# For example, to write a log:
# with open(log_path, 'a') as f:
#     f.write('...')
# To write a CSV:
# with open(csv_path, 'w', newline='') as f:
#     writer = csv.writer(f)
#     writer.writerow([...]) 
>>>>>>> strategy-risk-mgmt
