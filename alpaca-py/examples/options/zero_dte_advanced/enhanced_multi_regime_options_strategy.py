# Enhanced Multi-Regime Options Strategy
# (See README_AFTER_FORK.md for usage)

# --- Robust .env loading (must be at the very top) ---
import os
from dotenv import load_dotenv

def find_project_root_with_env(start_path):
    current = os.path.abspath(start_path)
    while not os.path.exists(os.path.join(current, '.env')) and current != os.path.dirname(current):
        current = os.path.dirname(current)
    return current

project_root = find_project_root_with_env(__file__)
dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=dotenv_path)

# Debug output
print(f"[DEBUG] .env path resolved to: {dotenv_path}")
print(f"[DEBUG] Current working directory: {os.getcwd()}")
api_key = os.getenv("ALPACA_API_KEY")
secret_key = os.getenv("ALPACA_SECRET_KEY")
print(f"[DEBUG] ALPACA_API_KEY: {api_key}")
print(f"[DEBUG] ALPACA_SECRET_KEY: {'*' * len(secret_key) if secret_key else None}")

import logging
from datetime import datetime, time as dtime, timedelta
from typing import List
import yfinance as yf
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, OptionLegRequest, GetOptionContractsRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
from alpaca.data.historical import StockHistoricalDataClient, OptionHistoricalDataClient
from alpaca.data.requests import StockLatestBarRequest, StockBarsRequest, OptionLatestQuoteRequest

# --- Logging Setup ---
log_dir = os.path.join(os.path.dirname(__file__), 'logs', datetime.now().strftime('%Y-%m-%d'))
os.makedirs(log_dir, exist_ok=True)
logfile = os.path.join(log_dir, f'strategy_{datetime.now().strftime("%H%M%S")}.log')
logging.basicConfig(
    filename=logfile,
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
logger = logging.getLogger(__name__)

# --- Risk/Profit/Position Management Classes ---
class RiskManager:
    def __init__(self):
        self.max_daily_loss = 0.03  # 3%
        self.max_trades_per_day = 2
        self.kelly_fraction = 0.5
        self.daily_pnl = 0.0
        self.trades_today = 0
    def can_trade(self, portfolio_value):
        if self.daily_pnl < -self.max_daily_loss * portfolio_value:
            logger.info("Max daily loss hit. No more trades today.")
            return False
        if self.trades_today >= self.max_trades_per_day:
            logger.info("Max trades per day hit.")
            return False
        return True
    def calculate_position_size(self, portfolio_value, strategy_type, max_risk):
        # Fractional Kelly, capped by max risk per trade
        kelly = self.kelly_fraction
        size = int((portfolio_value * kelly) // max_risk)
        return max(size, 1)

class ProfitManager:
    def should_take_profit(self, pnl, max_profit, strategy_type):
        # Take profit at 50% of max profit
        return pnl >= 0.5 * max_profit
    def should_stop_loss(self, pnl, entry_credit, strategy_type):
        # Stop loss at 100% of entry credit lost
        return pnl <= -1.0 * abs(entry_credit)

class PositionTracker:
    def __init__(self):
        self.positions = {}
    def add_position(self, symbol, data):
        self.positions[symbol] = data
    def update_position(self, symbol, data):
        if symbol in self.positions:
            self.positions[symbol].update(data)
    def remove_position(self, symbol):
        if symbol in self.positions:
            del self.positions[symbol]

# --- Main Strategy Class ---
class EnhancedMultiRegimeOptionsStrategy:
    def __init__(self, api_key, secret_key, paper=True):
        self.trading_client = TradingClient(api_key, secret_key, paper=paper)
        self.stock_data_client = StockHistoricalDataClient(api_key, secret_key)
        self.option_data_client = OptionHistoricalDataClient(api_key, secret_key)
        self.risk_manager = RiskManager()
        self.profit_manager = ProfitManager()
        self.position_tracker = PositionTracker()
        self.low_vol_threshold = 17
        self.high_vol_threshold = 18
        self.target_daily_return = 0.005
        self.daily_start_value = None
        self.trades_today = 0

    async def get_current_vix(self):
        try:
            vix = yf.Ticker("^VIX")
            hist = vix.history(period="5d")
            if len(hist) >= 2:
                current_vix = hist['Close'].iloc[-1]
                previous_vix = hist['Close'].iloc[-2]
                return current_vix, previous_vix
            else:
                logger.warning("VIX history data is too short or missing")
                return None, None
        except Exception as e:
            logger.error(f"Error getting VIX data: {e}")
            return None, None

    async def get_spy_price(self):
        try:
            bar_request = StockLatestBarRequest(symbol_or_symbols=["SPY"])
            bars = self.stock_data_client.get_stock_latest_bar(bar_request)
            if bars and "SPY" in bars and hasattr(bars["SPY"], "close"):
                return bars["SPY"].close
            return None
        except Exception as e:
            logger.error(f"Error getting SPY price: {e}")
            return None

    async def get_momentum_indicator(self):
        try:
            end_time = datetime.now()
            start_time = end_time - timedelta(days=5)
            bars_request = StockBarsRequest(
                symbol_or_symbols=["SPY"],
                timeframe="1Hour",
                start=start_time,
                end=end_time
            )
            bars = self.stock_data_client.get_stock_bars(bars_request)
            if "SPY" in bars:
                prices = [bar.close for bar in bars["SPY"]]
                if len(prices) >= 14:
                    rsi = self.calculate_rsi(prices)
                    if rsi > 70:
                        return -0.6
                    elif rsi < 30:
                        return 0.6
                    else:
                        return 0
            return 0
        except Exception as e:
            logger.error(f"Error calculating momentum: {e}")
            return 0

    def calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        if len(prices) < period + 1:
            return 50
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

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
            'bearish_momentum': momentum < -0.5,
            'spy_price': spy_price,
            'momentum': momentum
        }
        if conditions['high_volatility'] and conditions['vix_higher']:
            return "IRON_CONDOR", conditions
        elif conditions['low_volatility'] and not conditions['vix_higher']:
            return "DIAGONAL", conditions
        elif conditions['moderate_volatility']:
            if conditions['bullish_momentum'] and momentum > 0.3:
                return "PUT_CREDIT_SPREAD", conditions
            elif conditions['bearish_momentum'] and momentum < -0.3:
                return "CALL_CREDIT_SPREAD", conditions
            else:
                return "IRON_BUTTERFLY", conditions
        else:
            return "NO_TRADE", conditions

    async def check_existing_positions(self):
        try:
            positions = self.trading_client.get_all_positions()
            for position in positions:
                if hasattr(position, 'symbol') and 'SPY' in position.symbol:
                    await self.manage_position(position)
        except Exception as e:
            logger.error(f"Error checking positions: {e}")

    async def manage_position(self, position):
        try:
            symbol = position.symbol
            current_qty = float(position.qty)
            current_value = float(position.market_value)
            position_data = self.position_tracker.positions.get(symbol, {})
            if not position_data:
                logger.warning(f"No tracking data for position {symbol}")
                return
            entry_value = position_data.get('entry_value', 0)
            strategy_type = position_data.get('strategy_type', 'UNKNOWN')
            max_profit = position_data.get('max_profit', 0)
            current_pnl = current_value - entry_value
            if self.profit_manager.should_take_profit(current_pnl, max_profit, strategy_type):
                logger.info(f"Taking profit on {symbol}: PnL=${current_pnl:.2f}")
                await self.close_position(symbol, current_qty)
                return
            entry_credit = position_data.get('entry_credit', 0)
            if self.profit_manager.should_stop_loss(current_pnl, entry_credit, strategy_type):
                logger.info(f"Stopping loss on {symbol}: PnL=${current_pnl:.2f}")
                await self.close_position(symbol, current_qty)
                return
            self.position_tracker.update_position(symbol, {
                'current_value': current_value,
                'current_pnl': current_pnl,
                'last_check': datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Error managing position: {e}")

    async def close_position(self, symbol: str, quantity: float):
        try:
            side = OrderSide.BUY if quantity < 0 else OrderSide.SELL
            order = MarketOrderRequest(
                symbol=symbol,
                qty=abs(quantity),
                side=side,
                time_in_force=TimeInForce.DAY
            )
            result = self.trading_client.submit_order(order)
            logger.info(f"Closed position {symbol}: {result}")
            self.position_tracker.remove_position(symbol)
        except Exception as e:
            logger.error(f"Error closing position {symbol}: {e}")

    async def calculate_strategy_metrics(self, strategy_type: str, spy_price: float, contracts: int):
        base_credit = {
            "IRON_CONDOR": 0.5,
            "IRON_BUTTERFLY": 0.8,
            "PUT_CREDIT_SPREAD": 0.3,
            "CALL_CREDIT_SPREAD": 0.3,
            "DIAGONAL": -0.2
        }
        max_risk = {
            "IRON_CONDOR": 4.5,
            "IRON_BUTTERFLY": 2.2,
            "PUT_CREDIT_SPREAD": 2.7,
            "CALL_CREDIT_SPREAD": 2.7,
            "DIAGONAL": 1.5
        }
        return {
            'expected_credit': base_credit.get(strategy_type, 0) * contracts * 100,
            'max_risk': max_risk.get(strategy_type, 1) * contracts * 100,
            'max_profit': base_credit.get(strategy_type, 0) * contracts * 100
        }

    async def execute_strategy_with_risk_management(self, strategy_type: str, spy_price: float, portfolio_value: float):
        temp_contracts = 1
        metrics = await self.calculate_strategy_metrics(strategy_type, spy_price, temp_contracts)
        contracts = self.risk_manager.calculate_position_size(
            portfolio_value, strategy_type, metrics['max_risk']
        )
        metrics = await self.calculate_strategy_metrics(strategy_type, spy_price, contracts)
        logger.info(f"Strategy: {strategy_type}")
        logger.info(f"Contracts: {contracts}")
        logger.info(f"Expected Credit: ${metrics['expected_credit']:.2f}")
        logger.info(f"Max Risk: ${metrics['max_risk']:.2f}")
        logger.info(f"Max Profit: ${metrics['max_profit']:.2f}")
        if strategy_type == "IRON_CONDOR":
            success, message = await self.execute_iron_condor(spy_price, contracts)
        elif strategy_type == "DIAGONAL":
            success, message = await self.execute_diagonal(spy_price, contracts)
        elif strategy_type == "PUT_CREDIT_SPREAD":
            success, message = await self.execute_put_credit_spread(spy_price, contracts)
        elif strategy_type == "CALL_CREDIT_SPREAD":
            success, message = await self.execute_call_credit_spread(spy_price, contracts)
        elif strategy_type == "IRON_BUTTERFLY":
            success, message = await self.execute_iron_butterfly(spy_price, contracts)
        else:
            return False, "Unknown strategy type"
        if success:
            position_id = f"{strategy_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self.position_tracker.add_position(position_id, {
                'strategy_type': strategy_type,
                'entry_time': datetime.now().isoformat(),
                'contracts': contracts,
                'entry_credit': metrics['expected_credit'],
                'max_profit': metrics['max_profit'],
                'max_risk': metrics['max_risk'],
                'entry_value': metrics['expected_credit']
            })
            self.risk_manager.trades_today += 1
        return success, message

    async def execute_iron_condor(self, spy_price, contracts):
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
            calls = [c for c in option_contracts if c.type == 'call']
            puts = [c for c in option_contracts if c.type == 'put']
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
            logger.info(f"Iron Condor Setup ({contracts} contracts):")
            logger.info(f"Short Call: {short_call.strike_price} @ ${quotes[short_call.symbol].bid_price}")
            logger.info(f"Long Call:  {long_call.strike_price} @ ${quotes[long_call.symbol].ask_price}")
            logger.info(f"Short Put:  {short_put.strike_price} @ ${quotes[short_put.symbol].bid_price}")
            logger.info(f"Long Put:   {long_put.strike_price} @ ${quotes[long_put.symbol].ask_price}")
            logger.info(f"Expected Credit: ${credit * 100:.2f} per spread")
            order_legs = [
                self.build_option_leg(short_call.symbol, OrderSide.SELL),
                self.build_option_leg(long_call.symbol, OrderSide.BUY),
                self.build_option_leg(short_put.symbol, OrderSide.SELL),
                self.build_option_leg(long_put.symbol, OrderSide.BUY)
            ]
            return await self.submit_multi_leg_order(order_legs, contracts)
        except Exception as e:
            logger.error(f"Error executing iron condor: {e}")
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
            calls0.sort(key=lambda c: abs(c.strike_price - spy_price))
            calls7.sort(key=lambda c: abs(c.strike_price - spy_price))
            short_call = next((c for c in calls0 if c.strike_price >= spy_price), None)
            long_call = next((c for c in calls7 if c.strike_price == short_call.strike_price), None) if short_call else None
            if not short_call or not long_call:
                return False, "No suitable diagonal call found"
            symbols = [short_call.symbol, long_call.symbol]
            quotes = await self.get_option_quotes(symbols)
            if not quotes:
                return False, "Could not get option quotes"
            debit = (quotes[long_call.symbol].ask_price - quotes[short_call.symbol].bid_price)
            logger.info(f"Diagonal Spread Setup ({contracts} contracts):")
            logger.info(f"Long Call (7DTE):  {long_call.strike_price} @ ${quotes[long_call.symbol].ask_price}")
            logger.info(f"Short Call (0DTE): {short_call.strike_price} @ ${quotes[short_call.symbol].bid_price}")
            logger.info(f"Net Debit: ${debit * 100:.2f} per spread")
            order_legs = [
                self.build_option_leg(long_call.symbol, OrderSide.BUY),
                self.build_option_leg(short_call.symbol, OrderSide.SELL)
            ]
            return await self.submit_multi_leg_order(order_legs, contracts)
        except Exception as e:
            logger.error(f"Error executing diagonal: {e}")
            return False, f"Error executing diagonal: {e}"

    async def execute_put_credit_spread(self, spy_price, contracts):
        try:
            expiry = datetime.now().date()
            contracts_request = GetOptionContractsRequest(
                underlying_symbols=["SPY"],
                expiration_date=expiry,
                limit=1000
            )
            response = self.trading_client.get_option_contracts(contracts_request)
            puts = [c for c in getattr(response, 'option_contracts', []) if c.type == 'put']
            puts.sort(key=lambda c: abs(c.strike_price - spy_price))
            short_put = next((p for p in puts if p.strike_price <= spy_price), None)
            long_put = next((p for p in puts if p.strike_price == short_put.strike_price - 5), None) if short_put else None
            if not short_put or not long_put:
                return False, "No suitable put spread found"
            symbols = [short_put.symbol, long_put.symbol]
            quotes = await self.get_option_quotes(symbols)
            if not quotes:
                return False, "Could not get option quotes"
            credit = (quotes[short_put.symbol].bid_price - quotes[long_put.symbol].ask_price)
            logger.info(f"Put Credit Spread Setup ({contracts} contracts):")
            logger.info(f"Short Put: {short_put.strike_price} @ ${quotes[short_put.symbol].bid_price}")
            logger.info(f"Long Put:  {long_put.strike_price} @ ${quotes[long_put.symbol].ask_price}")
            logger.info(f"Expected Credit: ${credit * 100:.2f} per spread")
            order_legs = [
                self.build_option_leg(short_put.symbol, OrderSide.SELL),
                self.build_option_leg(long_put.symbol, OrderSide.BUY)
            ]
            return await self.submit_multi_leg_order(order_legs, contracts)
        except Exception as e:
            logger.error(f"Error executing put credit spread: {e}")
            return False, f"Error executing put credit spread: {e}"

    async def execute_call_credit_spread(self, spy_price, contracts):
        try:
            expiry = datetime.now().date()
            contracts_request = GetOptionContractsRequest(
                underlying_symbols=["SPY"],
                expiration_date=expiry,
                limit=1000
            )
            response = self.trading_client.get_option_contracts(contracts_request)
            calls = [c for c in getattr(response, 'option_contracts', []) if c.type == 'call']
            calls.sort(key=lambda c: abs(c.strike_price - spy_price))
            short_call = next((c for c in calls if c.strike_price >= spy_price), None)
            long_call = next((c for c in calls if c.strike_price == short_call.strike_price + 5), None) if short_call else None
            if not short_call or not long_call:
                return False, "No suitable call spread found"
            symbols = [short_call.symbol, long_call.symbol]
            quotes = await self.get_option_quotes(symbols)
            if not quotes:
                return False, "Could not get option quotes"
            credit = (quotes[short_call.symbol].bid_price - quotes[long_call.symbol].ask_price)
            logger.info(f"Call Credit Spread Setup ({contracts} contracts):")
            logger.info(f"Short Call: {short_call.strike_price} @ ${quotes[short_call.symbol].bid_price}")
            logger.info(f"Long Call:  {long_call.strike_price} @ ${quotes[long_call.symbol].ask_price}")
            logger.info(f"Expected Credit: ${credit * 100:.2f} per spread")
            order_legs = [
                self.build_option_leg(short_call.symbol, OrderSide.SELL),
                self.build_option_leg(long_call.symbol, OrderSide.BUY)
            ]
            return await self.submit_multi_leg_order(order_legs, contracts)
        except Exception as e:
            logger.error(f"Error executing call credit spread: {e}")
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
            calls = [c for c in option_contracts if c.type == 'call']
            puts = [c for c in option_contracts if c.type == 'put']
            calls.sort(key=lambda c: abs(c.strike_price - spy_price))
            puts.sort(key=lambda c: abs(c.strike_price - spy_price))
            atm_call = next((c for c in calls if c.strike_price >= spy_price), None)
            atm_put = next((p for p in puts if p.strike_price <= spy_price), None)
            if not atm_call or not atm_put:
                return False, "No suitable ATM call/put found"
            otm_call = next((c for c in calls if c.strike_price == atm_call.strike_price + 5), None)
            otm_put = next((p for p in puts if p.strike_price == atm_put.strike_price - 5), None)
            if not otm_call or not otm_put:
                return False, "No suitable OTM call/put found"
            symbols = [atm_call.symbol, otm_call.symbol, atm_put.symbol, otm_put.symbol]
            quotes = await self.get_option_quotes(symbols)
            if not quotes:
                return False, "Could not get option quotes"
            credit = (quotes[atm_call.symbol].bid_price + quotes[atm_put.symbol].bid_price -
                      quotes[otm_call.symbol].ask_price - quotes[otm_put.symbol].ask_price)
            logger.info(f"Iron Butterfly Setup ({contracts} contracts):")
            logger.info(f"ATM Call: {atm_call.strike_price} @ ${quotes[atm_call.symbol].bid_price}")
            logger.info(f"OTM Call: {otm_call.strike_price} @ ${quotes[otm_call.symbol].ask_price}")
            logger.info(f"ATM Put:  {atm_put.strike_price} @ ${quotes[atm_put.symbol].bid_price}")
            logger.info(f"OTM Put:  {otm_put.strike_price} @ ${quotes[otm_put.symbol].ask_price}")
            logger.info(f"Expected Credit: ${credit * 100:.2f} per spread")
            order_legs = [
                self.build_option_leg(atm_call.symbol, OrderSide.SELL),
                self.build_option_leg(otm_call.symbol, OrderSide.BUY),
                self.build_option_leg(atm_put.symbol, OrderSide.SELL),
                self.build_option_leg(otm_put.symbol, OrderSide.BUY)
            ]
            return await self.submit_multi_leg_order(order_legs, contracts)
        except Exception as e:
            logger.error(f"Error executing iron butterfly: {e}")
            return False, f"Error executing iron butterfly: {e}"

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
            logger.info("Multi-leg order placed successfully.")
            return True, f"Order submitted: {getattr(res, 'id', 'N/A')}"
        except Exception as e:
            logger.error(f"Error submitting multi-leg order: {e}")
            return False, f"Order execution failed: {e}"

    async def get_option_quotes(self, symbol_list):
        try:
            quote_request = OptionLatestQuoteRequest(symbol_or_symbols=symbol_list)
            quotes = self.option_data_client.get_option_latest_quote(quote_request)
            return quotes
        except Exception as e:
            logger.error(f"Error getting option quotes: {e}")
            return None

    async def run_strategy(self):
        print("[TRACE] Entered run_strategy()")
        logger.info("Starting enhanced multi-regime options strategy...")
        try:
            account = self.trading_client.get_account()
            portfolio_value = float(getattr(account, 'portfolio_value', 0))
            if self.daily_start_value is None:
                self.daily_start_value = portfolio_value
            daily_pnl = portfolio_value - self.daily_start_value
            daily_return = daily_pnl / self.daily_start_value if self.daily_start_value > 0 else 0
            logger.info(f"Portfolio value: ${portfolio_value:,.2f}")
            logger.info(f"Daily P&L: ${daily_pnl:,.2f} ({daily_return*100:.2f}%)")
            self.risk_manager.daily_pnl = daily_pnl
            await self.check_existing_positions()
            if daily_return >= self.target_daily_return:
                print("[TRACE] Exiting: daily_return >= target_daily_return")
                logger.info(f"Daily target reached: {daily_return*100:.2f}%")
                return
            if not self.risk_manager.can_trade(portfolio_value):
                print("[TRACE] Exiting: risk_manager.can_trade() is False")
                logger.info("Risk limits prevent new trades")
                return
            strategy, conditions = await self.analyze_market_conditions()
            print(f"[TRACE] Market analysis: {strategy}")
            logger.info(f"Market analysis: {strategy}")
            logger.info(f"Conditions: {conditions}")
            if strategy == "NO_TRADE":
                print("[TRACE] Exiting: strategy == NO_TRADE")
                logger.info("No trading conditions met")
                return
            spy_price = await self.get_spy_price()
            if not spy_price:
                print("[TRACE] Exiting: Could not get SPY price")
                logger.error("Could not get SPY price")
                return
            success, message = await self.execute_strategy_with_risk_management(
                strategy, spy_price, portfolio_value
            )
            print(f"[TRACE] Execution result: {success} - {message}")
            logger.info(f"Execution result: {success} - {message}")
        except Exception as e:
            print(f"[TRACE] Exception in run_strategy: {e}")
            logger.error(f"Error in run_strategy: {e}")

    def is_market_open(self):
        now = datetime.now().time()
        return dtime(9, 30) <= now <= dtime(16, 0)

    def reset_daily_counters(self):
        self.risk_manager.daily_pnl = 0.0
        self.risk_manager.trades_today = 0
        self.daily_start_value = None

# --- Usage Example ---
if __name__ == "__main__":
    print(">>> Script started")
    import asyncio
    try:
        api_key = os.getenv("ALPACA_API_KEY")
        secret_key = os.getenv("ALPACA_SECRET_KEY")
        if not api_key or not secret_key:
            print("Error: Alpaca API keys not found in environment variables or .env file.")
        else:
            print(">>> Keys loaded, running strategy...")
            strategy = EnhancedMultiRegimeOptionsStrategy(api_key, secret_key, paper=True)
            asyncio.run(strategy.run_strategy())
            print(">>> Strategy run complete")
    except Exception as e:
        print(f"Exception occurred: {e}") 