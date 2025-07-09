import asyncio
import logging
import os
import json
from datetime import datetime, timedelta, time as dtime
from typing import Dict, List
from dotenv import load_dotenv
import yfinance as yf
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient, OptionHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, OptionBarsRequest, OptionLatestQuoteRequest, StockLatestBarRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.requests import GetOptionContractsRequest, LimitOrderRequest, OptionLegRequest, MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass

# Setup logging to logs/ folder with timestamp
logs_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(logs_dir, exist_ok=True)
now_str = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
log_path = os.path.join(logs_dir, f"enhanced_strategy_{now_str}.log")
logging.basicConfig(
    filename=log_path,
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
logger = logging.getLogger(__name__)

def find_project_root_with_env(start_path):
    current = os.path.abspath(start_path)
    while not os.path.exists(os.path.join(current, '.env')) and current != os.path.dirname(current):
        current = os.path.dirname(current)
    return current

project_root = find_project_root_with_env(__file__)
dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=dotenv_path)

class RiskManager:
    def __init__(self, max_portfolio_risk: float = 0.02, max_daily_loss: float = 0.03):
        self.max_portfolio_risk = max_portfolio_risk
        self.max_daily_loss = max_daily_loss
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.max_trades_per_day = 3
        self.win_rate = 0.65
        self.avg_win_loss_ratio = 1.5
    def can_trade(self, portfolio_value: float) -> bool:
        if self.trades_today >= self.max_trades_per_day:
            logger.info(f"Max trades per day reached: {self.trades_today}")
            return False
        if self.daily_pnl <= -self.max_daily_loss * portfolio_value:
            logger.info(f"Daily loss limit reached: {self.daily_pnl}")
            return False
        return True
    def calculate_position_size(self, portfolio_value: float, strategy_type: str, max_risk_per_contract: float) -> int:
        p = self.win_rate
        q = 1 - p
        b = self.avg_win_loss_ratio
        kelly_fraction = (b * p - q) / b
        conservative_kelly = kelly_fraction * 0.25
        max_risk_amount = portfolio_value * min(self.max_portfolio_risk, conservative_kelly)
        risk_multipliers = {
            "IRON_CONDOR": 1.0,
            "IRON_BUTTERFLY": 1.2,
            "PUT_CREDIT_SPREAD": 0.8,
            "CALL_CREDIT_SPREAD": 0.8,
            "DIAGONAL": 0.6
        }
        adjusted_risk = max_risk_amount * risk_multipliers.get(strategy_type, 1.0)
        contracts = int(adjusted_risk / max_risk_per_contract)
        return max(1, min(contracts, 10))

class ProfitManager:
    def __init__(self):
        self.profit_targets = {
            "IRON_CONDOR": 0.5,
            "IRON_BUTTERFLY": 0.6,
            "PUT_CREDIT_SPREAD": 0.4,
            "CALL_CREDIT_SPREAD": 0.4,
            "DIAGONAL": 0.3
        }
        self.stop_loss_targets = {
            "IRON_CONDOR": 2.0,
            "IRON_BUTTERFLY": 2.5,
            "PUT_CREDIT_SPREAD": 2.0,
            "CALL_CREDIT_SPREAD": 2.0,
            "DIAGONAL": 1.5
        }
    def should_take_profit(self, current_pnl: float, max_profit: float, strategy_type: str) -> bool:
        target = self.profit_targets.get(strategy_type, 0.5)
        return current_pnl >= (max_profit * target)
    def should_stop_loss(self, current_pnl: float, entry_credit: float, strategy_type: str) -> bool:
        target = self.stop_loss_targets.get(strategy_type, 2.0)
        return current_pnl <= -(entry_credit * target)

class PositionTracker:
    def __init__(self):
        self.positions_file = os.path.join(logs_dir, "positions.json")
        self.positions = self.load_positions()
    def load_positions(self) -> Dict:
        try:
            with open(self.positions_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
    def save_positions(self):
        with open(self.positions_file, 'w') as f:
            json.dump(self.positions, f, indent=2)
    def add_position(self, position_id: str, position_data: Dict):
        self.positions[position_id] = position_data
        self.save_positions()
    def update_position(self, position_id: str, updates: Dict):
        if position_id in self.positions:
            self.positions[position_id].update(updates)
            self.save_positions()
    def remove_position(self, position_id: str):
        if position_id in self.positions:
            del self.positions[position_id]
            self.save_positions()

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
                timeframe=TimeFrame.Hour,
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

    # ... (Insert all execute_* methods and helpers as in your previous code) ...

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
                logger.info(f"Daily target reached: {daily_return*100:.2f}%")
                return
            if not self.risk_manager.can_trade(portfolio_value):
                logger.info("Risk limits prevent new trades")
                return
            strategy, conditions = await self.analyze_market_conditions()
            logger.info(f"Market analysis: {strategy}")
            logger.info(f"Conditions: {conditions}")
            if strategy == "NO_TRADE":
                logger.info("No trading conditions met")
                return
            spy_price = await self.get_spy_price()
            if not spy_price:
                logger.error("Could not get SPY price")
                return
            success, message = await self.execute_strategy_with_risk_management(
                strategy, spy_price, portfolio_value
            )
            logger.info(f"Execution result: {success} - {message}")
        except Exception as e:
            logger.error(f"Error in run_strategy: {e}")

    def is_market_open(self):
        now = datetime.now().time()
        return dtime(9, 30) <= now <= dtime(16, 0)

    def reset_daily_counters(self):
        self.risk_manager.daily_pnl = 0.0
        self.risk_manager.trades_today = 0
        self.daily_start_value = None

# Usage example
async def main():
    strategy = EnhancedMultiRegimeOptionsStrategy(
        api_key=os.getenv("ALPACA_API_KEY"),
        secret_key=os.getenv("ALPACA_SECRET_KEY"),
        paper=True
    )
    last_date = None
    while True:
        current_date = datetime.now().date()
        if last_date != current_date:
            strategy.reset_daily_counters()
            last_date = current_date
        if not strategy.is_market_open():
            logger.info("Market is closed. Sleeping for 10 minutes...")
            await asyncio.sleep(600)
            continue
        await strategy.run_strategy()
        logger.info("Sleeping for 5 minutes before next check...")
        await asyncio.sleep(300)

if __name__ == "__main__":
    asyncio.run(main()) 