<<<<<<< HEAD
import asyncio
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient, OptionHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, OptionBarsRequest, OptionLatestQuoteRequest, StockLatestBarRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.requests import GetOptionContractsRequest, LimitOrderRequest, OptionLegRequest, MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
from datetime import datetime, timedelta, time as dtime
import os
from dotenv import load_dotenv
import yfinance as yf

# Robustly find and load .env from the project root
# ... (same as in adaptive_options_strategy.py) ...
def find_project_root_with_env(start_path):
    current = os.path.abspath(start_path)
    while not os.path.exists(os.path.join(current, '.env')) and current != os.path.dirname(current):
        current = os.path.dirname(current)
    return current

project_root = find_project_root_with_env(__file__)
dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=dotenv_path)

class MultiRegimeOptionsStrategy:
    def __init__(self, api_key, secret_key, paper=True):
        self.trading_client = TradingClient(api_key, secret_key, paper=paper)
        self.stock_data_client = StockHistoricalDataClient(api_key, secret_key)
        self.option_data_client = OptionHistoricalDataClient(api_key, secret_key)
        self.low_vol_threshold = 17
        self.high_vol_threshold = 18
        self.max_risk_per_trade = 0.02

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
            print(f"Error getting VIX data: {e}")
            return None, None

    async def get_spy_price(self):
        try:
            # Use StockLatestBarRequest for latest price
            bar_request = StockLatestBarRequest(symbol_or_symbols=["SPY"])
            bars = self.stock_data_client.get_stock_latest_bar(bar_request)
            if bars and "SPY" in bars and hasattr(bars["SPY"], "close"):
                return bars["SPY"].close
            return None
        except Exception as e:
            print(f"Error getting SPY price: {e}")
            return None

    async def get_momentum_indicator(self):
        # Placeholder: implement RSI, MACD, or moving average logic here
        # For now, return 0 (neutral)
        return 0

    async def analyze_market_conditions(self):
        current_vix, previous_vix = await self.get_current_vix()
        spy_price = await self.get_spy_price()
        momentum = await self.get_momentum_indicator()
        conditions = {
            'current_vix': current_vix,
            'previous_vix': previous_vix,
            'vix_higher': current_vix > previous_vix if current_vix and previous_vix else False,
            'low_volatility': current_vix < self.low_vol_threshold if current_vix else False,
            'moderate_volatility': self.low_vol_threshold <= current_vix <= self.high_vol_threshold if current_vix else False,
            'high_volatility': current_vix > self.high_vol_threshold if current_vix else False,
            'bullish_momentum': momentum > 0.5,
            'bearish_momentum': momentum < -0.5
        }
        if conditions['vix_higher'] and conditions['high_volatility']:
            return "IRON_CONDOR", conditions
        elif conditions['low_volatility']:
            return "DIAGONAL", conditions
        elif conditions['moderate_volatility']:
            if conditions['bullish_momentum']:
                return "PUT_CREDIT_SPREAD", conditions
            elif conditions['bearish_momentum']:
                return "CALL_CREDIT_SPREAD", conditions
            else:
                return "IRON_BUTTERFLY", conditions
        else:
            return "NO_TRADE", conditions

    def calculate_position_size(self, portfolio_value, strategy_type):
        max_risk_amount = portfolio_value * self.max_risk_per_trade
        # Placeholder: adjust per strategy
        estimated_max_risk = 700 if strategy_type == "IRON_CONDOR" else 150
        contracts = int(max_risk_amount / estimated_max_risk)
        return max(1, min(contracts, 20))

    def build_option_leg(self, symbol, side, ratio_qty=1):
        return OptionLegRequest(
            symbol=symbol,
            side=side,
            ratio_qty=ratio_qty
        )

    async def submit_multi_leg_order(self, order_legs, contracts):
        try:
            req = MarketOrderRequest(
                qty=contracts,
                order_class=OrderClass.MLEG,
                time_in_force=TimeInForce.DAY,
                legs=order_legs
            )
            res = self.trading_client.submit_order(req)
            print("Multi-leg order placed successfully.")
            return True, f"Order submitted: {getattr(res, 'id', 'N/A')}"
        except Exception as e:
            print(f"Error submitting multi-leg order: {e}")
            return False, f"Order execution failed: {e}"

    async def execute_iron_condor(self, spy_price, contracts):
        try:
            # Find short call/put near ATM, long call/put 5 strikes away
            expiry = datetime.now().date()
            contracts_request = GetOptionContractsRequest(
                underlying_symbols=["SPY"],
                expiration_date=expiry,
                limit=1000
            )
            response = self.trading_client.get_option_contracts(contracts_request)
            option_contracts = getattr(response, 'option_contracts', None)
            if option_contracts is None:
                option_contracts = []
            # Debug: Print expiry, contract count, types, sample contracts, strikes
            print("[Iron Condor] Expiry used:", expiry)
            print("[Iron Condor] Total contracts returned:", len(option_contracts))
            print("[Iron Condor] Types found:", set(c.type for c in option_contracts))
            print("[Iron Condor] First 5 contracts:")
            for c in option_contracts[:5]:
                print(vars(c))
            calls = [c for c in option_contracts if c.type == 'call']
            puts = [c for c in option_contracts if c.type == 'put']
            print("[Iron Condor] Call strikes:", sorted(set(c.strike_price for c in calls)))
            print("[Iron Condor] Put strikes:", sorted(set(p.strike_price for p in puts)))
            # Short call: closest above spot
            calls.sort(key=lambda c: abs(c.strike_price - spy_price))
            puts.sort(key=lambda c: abs(c.strike_price - spy_price))
            short_call = next((c for c in calls if c.strike_price >= spy_price), None)
            short_put = next((p for p in puts if p.strike_price <= spy_price), None)
            if not short_call or not short_put:
                return False, "No suitable short call/put found"
            long_call = next((c for c in calls if c.strike_price == short_call.strike_price + 5), None)
            long_put = next((p for p in puts if p.strike_price == short_put.strike_price - 5), None)
            if not long_call or not long_put:
                return False, "No suitable long call/put found"
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
            order_legs = [
                self.build_option_leg(short_call.symbol, OrderSide.SELL),
                self.build_option_leg(long_call.symbol, OrderSide.BUY),
                self.build_option_leg(short_put.symbol, OrderSide.SELL),
                self.build_option_leg(long_put.symbol, OrderSide.BUY)
            ]
            return await self.submit_multi_leg_order(order_legs, contracts)
        except Exception as e:
            return False, f"Error executing iron condor: {e}"

    async def execute_diagonal(self, spy_price, contracts):
        try:
            expiry0 = datetime.now().date()
            expiry7 = expiry0 + timedelta(days=7)
            contracts_request0 = GetOptionContractsRequest(
                underlying_symbols=["SPY"],
                expiration_date=expiry0,
                limit=1000
            )
            contracts_request7 = GetOptionContractsRequest(
                underlying_symbols=["SPY"],
                expiration_date=expiry7,
                limit=1000
            )
            resp0 = self.trading_client.get_option_contracts(contracts_request0)
            resp7 = self.trading_client.get_option_contracts(contracts_request7)
            calls0 = [c for c in getattr(resp0, 'option_contracts', []) if c.type == 'call']
            calls7 = [c for c in getattr(resp7, 'option_contracts', []) if c.type == 'call']
            # Debug: Print expiry, contract count, types, sample contracts, strikes
            print("[Diagonal] Expiry0 used:", expiry0)
            print("[Diagonal] Total contracts returned (0DTE):", len(calls0))
            print("[Diagonal] Call strikes (0DTE):", sorted(set(c.strike_price for c in calls0)))
            print("[Diagonal] Expiry7 used:", expiry7)
            print("[Diagonal] Total contracts returned (7DTE):", len(calls7))
            print("[Diagonal] Call strikes (7DTE):", sorted(set(c.strike_price for c in calls7)))
            # Find closest strike in both
            calls0.sort(key=lambda c: abs(c.strike_price - spy_price))
            calls7.sort(key=lambda c: abs(c.strike_price - spy_price))
            short_call = calls0[0] if calls0 else None
            long_call = None
            if short_call:
                long_call = next((c for c in calls7 if abs(c.strike_price - short_call.strike_price) < 0.5), None)
            if not short_call or not long_call:
                return False, "No suitable diagonal strikes found"
            symbols = [long_call.symbol, short_call.symbol]
            quotes = await self.get_option_quotes(symbols)
            if not quotes:
                return False, "Could not get option quotes"
            net_debit = (quotes[long_call.symbol].ask_price - quotes[short_call.symbol].bid_price)
            print(f"Diagonal Spread Setup ({contracts} contracts):")
            print(f"Long Call (7DTE):  {long_call.strike_price} @ ${quotes[long_call.symbol].ask_price}")
            print(f"Short Call (0DTE): {short_call.strike_price} @ ${quotes[short_call.symbol].bid_price}")
            print(f"Net Debit: ${net_debit * 100:.2f} per spread")
            order_legs = [
                self.build_option_leg(long_call.symbol, OrderSide.BUY),
                self.build_option_leg(short_call.symbol, OrderSide.SELL)
            ]
            return await self.submit_multi_leg_order(order_legs, contracts)
        except Exception as e:
            return False, f"Error executing diagonal: {e}"

    async def execute_call_credit_spread(self, spy_price, contracts):
        try:
            expiry = datetime.now().date()
            contracts_request = GetOptionContractsRequest(
                underlying_symbols=["SPY"],
                expiration_date=expiry,
                limit=1000
            )
            response = self.trading_client.get_option_contracts(contracts_request)
            option_contracts = getattr(response, 'option_contracts', None)
            if option_contracts is None:
                option_contracts = []
            # Debug: Print expiry, contract count, types, sample contracts, strikes
            print("[Call Credit Spread] Expiry used:", expiry)
            print("[Call Credit Spread] Total contracts returned:", len(option_contracts))
            print("[Call Credit Spread] Types found:", set(c.type for c in option_contracts))
            print("[Call Credit Spread] First 5 contracts:")
            for c in option_contracts[:5]:
                print(vars(c))
            calls = [c for c in option_contracts if c.type == 'call']
            print("[Call Credit Spread] Call strikes:", sorted(set(c.strike_price for c in calls)))
            # Sort calls by strike closest above spot
            calls.sort(key=lambda c: abs(c.strike_price - spy_price))
            short_call = next((c for c in calls if c.strike_price >= spy_price), None)
            if not short_call:
                return False, "No suitable short call found"
            # Find long call 5–10 strikes above
            candidates = [c for c in calls if 5 <= (c.strike_price - short_call.strike_price) <= 10]
            if not candidates:
                return False, "No suitable long call found"
            long_call = candidates[0]
            symbols = [short_call.symbol, long_call.symbol]
            quotes = await self.get_option_quotes(symbols)
            if not quotes or short_call.symbol not in quotes or long_call.symbol not in quotes:
                return False, "Could not get option quotes"
            short_call_bid = quotes[short_call.symbol].bid_price
            long_call_ask = quotes[long_call.symbol].ask_price
            net_credit = short_call_bid - long_call_ask
            print(f"Call Credit Spread Setup ({contracts} contracts):")
            print(f"Sell Call: {short_call.strike_price} @ ${short_call_bid}")
            print(f"Buy Call:  {long_call.strike_price} @ ${long_call_ask}")
            print(f"Net Credit: ${net_credit * 100:.2f} per spread")
            order_legs = [
                self.build_option_leg(short_call.symbol, OrderSide.SELL),
                self.build_option_leg(long_call.symbol, OrderSide.BUY)
            ]
            return await self.submit_multi_leg_order(order_legs, contracts)
        except Exception as e:
            return False, f"Error executing call credit spread: {e}"

    async def execute_iron_butterfly(self, spy_price, contracts):
        try:
            expiry = datetime.now().date()
            contracts_request = GetOptionContractsRequest(
                underlying_symbols=["SPY"],
                expiration_date=expiry,
                limit=1000
            )
            response = self.trading_client.get_option_contracts(contracts_request)
            option_contracts = getattr(response, 'option_contracts', None)
            if option_contracts is None:
                option_contracts = []
            # Debug: Print expiry, contract count, types, sample contracts, expirations
            print("[Iron Butterfly] Expiry used:", expiry)
            print("[Iron Butterfly] Total contracts returned:", len(option_contracts))
            print("[Iron Butterfly] Types found:", set(c.type for c in option_contracts))
            print("[Iron Butterfly] First 5 contracts:")
            for c in option_contracts[:5]:
                print(vars(c))
            expiries = set(getattr(c, 'expiration_date', None) for c in option_contracts)
            expiries_sorted = sorted(e for e in expiries if e is not None)
            print("[Iron Butterfly] Unique expirations in contracts:", expiries_sorted)
            calls = [c for c in option_contracts if c.type == 'call']
            puts = [c for c in option_contracts if c.type == 'put']
            print("[Iron Butterfly] Call strikes:", sorted(set(c.strike_price for c in calls)))
            print("[Iron Butterfly] Put strikes:", sorted(set(p.strike_price for p in puts)))
            # ATM strike: closest to spot
            all_strikes = sorted(set([c.strike_price for c in calls] + [p.strike_price for p in puts]), key=lambda x: abs(x - spy_price))
            if not all_strikes:
                return False, "No strikes found"
            atm_strike = all_strikes[0]
            # Debug prints for available strikes
            print("Available call strikes:", sorted([c.strike_price for c in calls]))
            print("Available put strikes:", sorted([p.strike_price for p in puts]))
            print("ATM strike selected:", atm_strike)
            # Sell ATM call and put (loosen tolerance to <=0.05)
            short_call = next((c for c in calls if abs(c.strike_price - atm_strike) <= 0.05), None)
            short_put = next((p for p in puts if abs(p.strike_price - atm_strike) <= 0.05), None)
            if not short_call or not short_put:
                return False, "No suitable ATM call/put found"
            # Buy wings 2–3 strikes away
            call_wings = sorted([c for c in calls if 2 <= (c.strike_price - atm_strike) <= 3], key=lambda c: c.strike_price)
            put_wings = sorted([p for p in puts if 2 <= (atm_strike - p.strike_price) <= 3], key=lambda p: -p.strike_price)
            if not call_wings or not put_wings:
                return False, "No suitable wings found"
            long_call = call_wings[0]
            long_put = put_wings[0]
            symbols = [short_call.symbol, long_call.symbol, short_put.symbol, long_put.symbol]
            quotes = await self.get_option_quotes(symbols)
            if not quotes:
                return False, "Could not get option quotes"
            credit = (quotes[short_call.symbol].bid_price + quotes[short_put.symbol].bid_price -
                      quotes[long_call.symbol].ask_price - quotes[long_put.symbol].ask_price)
            print(f"Iron Butterfly Setup ({contracts} contracts):")
            print(f"Short Call: {short_call.strike_price} @ ${quotes[short_call.symbol].bid_price}")
            print(f"Long Call:  {long_call.strike_price} @ ${quotes[long_call.symbol].ask_price}")
            print(f"Short Put:  {short_put.strike_price} @ ${quotes[short_put.symbol].bid_price}")
            print(f"Long Put:   {long_put.strike_price} @ ${quotes[long_put.symbol].ask_price}")
            print(f"Expected Credit: ${credit * 100:.2f} per spread")
            order_legs = [
                self.build_option_leg(short_call.symbol, OrderSide.SELL),
                self.build_option_leg(long_call.symbol, OrderSide.BUY),
                self.build_option_leg(short_put.symbol, OrderSide.SELL),
                self.build_option_leg(long_put.symbol, OrderSide.BUY)
            ]
            return await self.submit_multi_leg_order(order_legs, contracts)
        except Exception as e:
            return False, f"Error executing iron butterfly: {e}"

    async def execute_put_credit_spread(self, spy_price, contracts):
        try:
            expiry = datetime.now().date()
            contracts_request = GetOptionContractsRequest(
                underlying_symbols=["SPY"],
                expiration_date=expiry,
                limit=1000
            )
            response = self.trading_client.get_option_contracts(contracts_request)
            option_contracts = getattr(response, 'option_contracts', None)
            if option_contracts is None:
                option_contracts = []
            # Debug: Print expiry, contract count, types, sample contracts, strikes
            print("[Put Credit Spread] Expiry used:", expiry)
            print("[Put Credit Spread] Total contracts returned:", len(option_contracts))
            print("[Put Credit Spread] Types found:", set(c.type for c in option_contracts))
            print("[Put Credit Spread] First 5 contracts:")
            for c in option_contracts[:5]:
                print(vars(c))
            puts = [c for c in option_contracts if c.type == 'put']
            print("[Put Credit Spread] Put strikes:", sorted(set(p.strike_price for p in puts)))
            # Sort puts by strike closest below spot
            puts.sort(key=lambda p: abs(p.strike_price - spy_price))
            short_put = next((p for p in puts if p.strike_price <= spy_price), None)
            if not short_put:
                return False, "No suitable short put found"
            # Find long put 5–10 strikes below
            candidates = [p for p in puts if 5 <= (short_put.strike_price - p.strike_price) <= 10]
            if not candidates:
                return False, "No suitable long put found"
            long_put = candidates[0]
            symbols = [short_put.symbol, long_put.symbol]
            quotes = await self.get_option_quotes(symbols)
            if not quotes or short_put.symbol not in quotes or long_put.symbol not in quotes:
                return False, "Could not get option quotes"
            short_put_bid = quotes[short_put.symbol].bid_price
            long_put_ask = quotes[long_put.symbol].ask_price
            net_credit = short_put_bid - long_put_ask
            print(f"Put Credit Spread Setup ({contracts} contracts):")
            print(f"Sell Put: {short_put.strike_price} @ ${short_put_bid}")
            print(f"Buy Put:  {long_put.strike_price} @ ${long_put_ask}")
            print(f"Net Credit: ${net_credit * 100:.2f} per spread")
            order_legs = [
                self.build_option_leg(short_put.symbol, OrderSide.SELL),
                self.build_option_leg(long_put.symbol, OrderSide.BUY)
            ]
            return await self.submit_multi_leg_order(order_legs, contracts)
        except Exception as e:
            return False, f"Error executing put credit spread: {e}"

    async def run_strategy(self):
        print("Starting multi-regime options strategy...")
        account = self.trading_client.get_account()
        portfolio_value = getattr(account, 'portfolio_value', None)
        if portfolio_value is not None:
            try:
                portfolio_value = float(portfolio_value)
            except Exception:
                portfolio_value = None
        if portfolio_value is None:
            print("Could not get portfolio value from account.")
            return
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
        elif strategy == "PUT_CREDIT_SPREAD":
            success, message = await self.execute_put_credit_spread(spy_price, contracts)
        elif strategy == "CALL_CREDIT_SPREAD":
            success, message = await self.execute_call_credit_spread(spy_price, contracts)
        elif strategy == "IRON_BUTTERFLY":
            success, message = await self.execute_iron_butterfly(spy_price, contracts)
        print(f"Execution result: {success} - {message}")

    async def get_option_quotes(self, symbol_list):
        try:
            quote_request = OptionLatestQuoteRequest(symbol_or_symbols=symbol_list)
            quotes = self.option_data_client.get_option_latest_quote(quote_request)
            return quotes
        except Exception as e:
            print(f"Error getting option quotes: {e}")
            return None

    def create_option_order(self, symbol, side, quantity, limit_price):
        return LimitOrderRequest(
            symbol=symbol,
            qty=quantity,
            side=side,
            time_in_force=TimeInForce.DAY,
            limit_price=round(limit_price, 2)
        )

# Usage example
async def main():
    strategy = MultiRegimeOptionsStrategy(
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
log_path = os.path.join(logs_dir, f"multi_regime_{now_str}.log")
csv_path = os.path.join(logs_dir, f"multi_regime_{now_str}.csv")

# Wherever you write logs or CSVs, use log_path/csv_path instead of a root-level file
# For example, to write a log:
# with open(log_path, 'a') as f:
#     f.write('...')
# To write a CSV:
# with open(csv_path, 'w', newline='') as f:
#     writer = csv.writer(f)
#     writer.writerow([...]) 
>>>>>>> strategy-risk-mgmt
