from lumibot.strategies.strategy import Strategy
from datetime import datetime, timedelta
import yfinance as yf

class AdaptiveOptionsLumibot(Strategy):
    def initialize(self):
        self.symbol = "SPY"
        self.low_vol_threshold = 17
        self.high_vol_threshold = 18
        self.max_risk_per_trade = 0.02
        self.iron_condor_target_profit = 0.25
        self.last_trade_day = None
        self.set_universe([self.symbol])
        self.schedule_function(self.check_and_trade, date_rule="every_day", time_rule="market_open")

    def get_current_vix(self):
        vix = yf.Ticker("^VIX")
        hist = vix.history(period="5d")
        if len(hist) >= 2:
            current_vix = hist['Close'].iloc[-1]
            previous_vix = hist['Close'].iloc[-2]
            return current_vix, previous_vix
        else:
            self.log(f"VIX history data is too short or missing: {hist}")
            return None, None

    def analyze_market_conditions(self):
        current_vix, previous_vix = self.get_current_vix()
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

    def find_target_delta_options(self, spy_price, target_delta=20, dte=0):
        expiry = self.get_datetime().date() + timedelta(days=dte)
        contracts = self.get_option_chains(self.symbol, expiry)
        target_call_strike = spy_price * (1 + target_delta/100 * 0.1)
        target_put_strike = spy_price * (1 - target_delta/100 * 0.1)
        call_options = []
        put_options = []
        for contract in contracts:
            if contract["option_type"] == "call":
                if abs(contract["strike"] - target_call_strike) < 10:
                    call_options.append(contract)
            elif contract["option_type"] == "put":
                if abs(contract["strike"] - target_put_strike) < 10:
                    put_options.append(contract)
        call_options.sort(key=lambda x: abs(x["strike"] - target_call_strike))
        put_options.sort(key=lambda x: abs(x["strike"] - target_put_strike))
        return call_options[:5], put_options[:5]

    def calculate_position_size(self, portfolio_value, strategy_type):
        max_risk_amount = portfolio_value * self.max_risk_per_trade
        if strategy_type == "IRON_CONDOR":
            estimated_max_risk = 700
            contracts = int(max_risk_amount / estimated_max_risk)
        elif strategy_type == "DIAGONAL":
            estimated_max_risk = 150
            contracts = int(max_risk_amount / estimated_max_risk)
        else:
            contracts = 1
        return max(1, min(contracts, 20))

    def check_and_trade(self):
        today = self.get_datetime().date()
        if self.last_trade_day == today:
            return  # Only one trade per day
        self.last_trade_day = today
        market_analysis, conditions = self.analyze_market_conditions()
        self.log(f"Market analysis: {market_analysis}")
        self.log(f"Conditions: {conditions}")
        portfolio_value = self.get_portfolio_value()
        spy_price = self.get_last_price(self.symbol)
        contracts = self.calculate_position_size(portfolio_value, market_analysis)
        if market_analysis == "IRON_CONDOR":
            self.execute_iron_condor(spy_price, contracts)
        elif market_analysis == "DIAGONAL":
            self.execute_diagonal(spy_price, contracts)
        else:
            self.log("No trading conditions met today")

    def execute_iron_condor(self, spy_price, contracts):
        call_options, put_options = self.find_target_delta_options(spy_price, target_delta=20, dte=0)
        if not call_options or not put_options:
            self.log("Could not find suitable option contracts for iron condor")
            return
        short_call = call_options[0]
        short_put = put_options[0]
        long_call_strike = short_call["strike"] + 5
        long_put_strike = short_put["strike"] - 5
        long_call = next((c for c in call_options if c["strike"] == long_call_strike), None)
        long_put = next((p for p in put_options if p["strike"] == long_put_strike), None)
        if not long_call or not long_put:
            self.log("Could not find long option contracts for iron condor")
            return
        self.log(f"Placing Iron Condor: Short Call {short_call['strike']}, Long Call {long_call['strike']}, Short Put {short_put['strike']}, Long Put {long_put['strike']}")
        self.place_order(
            symbol=short_call["symbol"],
            quantity=contracts,
            side="SELL_TO_OPEN",
            order_type="MARKET"
        )
        self.place_order(
            symbol=long_call["symbol"],
            quantity=contracts,
            side="BUY_TO_OPEN",
            order_type="MARKET"
        )
        self.place_order(
            symbol=short_put["symbol"],
            quantity=contracts,
            side="SELL_TO_OPEN",
            order_type="MARKET"
        )
        self.place_order(
            symbol=long_put["symbol"],
            quantity=contracts,
            side="BUY_TO_OPEN",
            order_type="MARKET"
        )
        self.log("Iron condor orders placed.")

    def execute_diagonal(self, spy_price, contracts):
        dte0_calls, _ = self.find_target_delta_options(spy_price, target_delta=40, dte=0)
        dte7_calls, _ = self.find_target_delta_options(spy_price, target_delta=40, dte=7)
        if not dte0_calls or not dte7_calls:
            self.log("Could not find suitable option contracts for diagonal spread")
            return
        target_strike = None
        long_call = None
        short_call = None
        for long_contract in dte7_calls:
            for short_contract in dte0_calls:
                if abs(long_contract["strike"] - short_contract["strike"]) < 0.5:
                    target_strike = long_contract["strike"]
                    long_call = long_contract
                    short_call = short_contract
                    break
            if target_strike:
                break
        if not long_call or not short_call:
            self.log("Could not find matching strike options for diagonal spread")
            return
        self.log(f"Placing Diagonal Spread: Long Call (7DTE) {long_call['strike']}, Short Call (0DTE) {short_call['strike']}")
        self.place_order(
            symbol=long_call["symbol"],
            quantity=contracts,
            side="BUY_TO_OPEN",
            order_type="MARKET"
        )
        self.place_order(
            symbol=short_call["symbol"],
            quantity=contracts,
            side="SELL_TO_OPEN",
            order_type="MARKET"
        )
        self.log("Diagonal spread orders placed.")

# Example usage for backtesting (in a separate script or main block):
if __name__ == "__main__":
    from lumibot.backtesting import YahooDataBacktesting
    broker = YahooDataBacktesting(
        start_date=datetime(2023, 1, 1),
        end_date=datetime(2023, 12, 31),
        symbols=["SPY"]
    )
    strategy = AdaptiveOptionsLumibot(broker=broker)
    strategy.backtest() 