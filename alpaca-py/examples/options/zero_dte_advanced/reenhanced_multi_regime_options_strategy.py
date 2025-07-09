import asyncio
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient, OptionHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, OptionBarsRequest, OptionLatestQuoteRequest, StockLatestBarRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.requests import GetOptionContractsRequest, LimitOrderRequest, OptionLegRequest, MarketOrderRequest, ClosePositionRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
from datetime import datetime, timedelta, time as dtime
import os
from dotenv import load_dotenv
import yfinance as yf
import csv
import math

def find_project_root_with_env(start_path):
    current = os.path.abspath(start_path)
    while not os.path.exists(os.path.join(current, '.env')) and current != os.path.dirname(current):
        current = os.path.dirname(current)
    return current

project_root = find_project_root_with_env(__file__)
dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=dotenv_path)

class RiskManager:
    def __init__(self, max_risk_per_trade=0.02, max_daily_loss=0.03, max_trades_per_day=3, kelly_fraction=0.25):
        self.max_risk_per_trade = max_risk_per_trade
        self.max_daily_loss = max_daily_loss
        self.max_trades_per_day = max_trades_per_day
        self.kelly_fraction = kelly_fraction
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.daily_start_value = None
        self.win_rate = 0.65  # target win rate
        self.win_loss_ratio = 1.5  # target win/loss ratio
        self.strategy_multipliers = {
            "IRON_CONDOR": 1.0,
            "DIAGONAL": 0.6,
            "PUT_CREDIT_SPREAD": 0.8,
            "CALL_CREDIT_SPREAD": 0.8,
            "IRON_BUTTERFLY": 0.7
        }

    def can_trade(self, portfolio_value):
        if self.daily_pnl < -self.max_daily_loss * portfolio_value:
            print("[RiskManager] Max daily loss hit. No more trades today.")
            return False
        if self.trades_today >= self.max_trades_per_day:
            print("[RiskManager] Max trades per day hit.")
            return False
        return True

    def calculate_kelly_position(self, portfolio_value, strategy_type, max_risk):
        # Kelly formula: f* = (bp - q) / b
        # b = win/loss ratio, p = win rate, q = 1-p
        b = self.win_loss_ratio
        p = self.win_rate
        q = 1 - p
        kelly = (b * p - q) / b
        kelly = max(kelly, 0.01)  # never go below 1%
        kelly *= self.kelly_fraction
        multiplier = self.strategy_multipliers.get(strategy_type, 1.0)
        size = int((portfolio_value * kelly * multiplier) // max_risk)
        return max(size, 1)

    def reset_daily_counters(self):
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.daily_start_value = None

class MultiRegimeOptionsStrategy:
    def __init__(self, api_key, secret_key, paper=True):
        self.trading_client = TradingClient(api_key, secret_key, paper=paper)
        self.stock_data_client = StockHistoricalDataClient(api_key, secret_key)
        self.option_data_client = OptionHistoricalDataClient(api_key, secret_key)
        self.low_vol_threshold = 17
        self.high_vol_threshold = 18
        self.risk_manager = RiskManager()
        self.last_trade_date = None
        self.log_dir = os.path.join(os.path.dirname(__file__), 'logs', datetime.now().strftime('%Y-%m-%d'))
        os.makedirs(self.log_dir, exist_ok=True)
        self.log_file = os.path.join(self.log_dir, f"trades_{datetime.now().strftime('%H%M%S')}.csv")
        if not os.path.exists(self.log_file):
            with open(self.log_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['timestamp', 'strategy', 'contracts', 'entry_price', 'exit_price', 'pnl'])

    def log_trade(self, strategy, contracts, entry_price, exit_price, pnl):
        with open(self.log_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().isoformat(),
                strategy,
                contracts,
                entry_price,
                exit_price,
                pnl
            ])

    def get_open_option_positions(self):
        # Fetch all open positions from Alpaca
        try:
            positions = self.trading_client.get_all_positions()
        except Exception as e:
            print(f"[Error] Failed to fetch positions: {e}")
            return []
        option_positions = []
        for pos in positions:
            # Support both dict and object style
            asset_class = getattr(pos, 'asset_class', None) if not isinstance(pos, dict) else pos.get('asset_class')
            if asset_class == 'option':
                try:
                    entry_price = getattr(pos, 'avg_entry_price', None) if not isinstance(pos, dict) else pos.get('avg_entry_price')
                    if entry_price is not None:
                        entry_price = float(entry_price)
                    else:
                        continue
                    current_price = getattr(pos, 'current_price', None) if not isinstance(pos, dict) else pos.get('current_price')
                    if current_price is not None:
                        current_price = float(current_price)
                    else:
                        current_price = entry_price
                    qty = getattr(pos, 'qty', None) if not isinstance(pos, dict) else pos.get('qty')
                    if qty is not None:
                        contracts = abs(int(float(qty)))
                    else:
                        continue
                    symbol = getattr(pos, 'symbol', None) if not isinstance(pos, dict) else pos.get('symbol')
                    if symbol is None:
                        continue
                    max_credit = entry_price
                    strategy = 'UNKNOWN'
                    option_positions.append({
                        'strategy': strategy,
                        'contracts': contracts,
                        'entry_price': entry_price,
                        'current_price': current_price,
                        'max_credit': max_credit,
                        'symbol': symbol,
                        'raw': pos
                    })
                except Exception as e:
                    print(f"[Error] Parsing position {pos}: {e}")
        return option_positions

    async def check_and_manage_positions(self):
        open_positions = self.get_open_option_positions()
        for pos in open_positions:
            profit_target = pos['max_credit'] * 0.5
            stop_loss = pos['max_credit'] * 1.0
            open_pnl = (pos['entry_price'] - pos['current_price']) * 100 * pos['contracts']
            if open_pnl >= profit_target * 100 * pos['contracts']:
                # Take profit
                await self.close_position(pos)
                self.risk_manager.daily_pnl += open_pnl
                self.log_trade(pos['strategy'], pos['contracts'], pos['entry_price'], pos['current_price'], open_pnl)
                print(f"[Profit] Closed {pos['strategy']} {pos['symbol']} for profit: ${open_pnl:.2f}")
            elif open_pnl <= -stop_loss * 100 * pos['contracts']:
                # Stop loss
                await self.close_position(pos)
                self.risk_manager.daily_pnl += open_pnl
                self.log_trade(pos['strategy'], pos['contracts'], pos['entry_price'], pos['current_price'], open_pnl)
                print(f"[StopLoss] Closed {pos['strategy']} {pos['symbol']} for loss: ${open_pnl:.2f}")

    async def close_position(self, position):
        # Close the position using Alpaca API
        try:
            print(f"[Close] Closing position: {position['symbol']} ({position['contracts']} contracts)")
            # Alpaca's close_position only needs the symbol
            self.trading_client.close_position(position['symbol'])
            print(f"[Close] Close order sent for {position['symbol']}")
        except Exception as e:
            print(f"[Error] Failed to close position {position['symbol']}: {e}")

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
            bar_request = StockLatestBarRequest(symbol_or_symbols=["SPY"])
            bars = self.stock_data_client.get_stock_latest_bar(bar_request)
            if bars and "SPY" in bars and hasattr(bars["SPY"], "close"):
                return bars["SPY"].close
            return None
        except Exception as e:
            print(f"Error getting SPY price: {e}")
            return None

    async def get_momentum_indicator(self):
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

    def calculate_position_size(self, portfolio_value, strategy_type, strike_width=5, credit_received=1.0):
        # Max risk per trade (2% of portfolio)
        max_risk_per_trade = portfolio_value * 0.02
        # Calculate max loss per contract by strategy
        if strategy_type == "IRON_CONDOR":
            # Max loss = (width of spreads - net credit) * 100
            max_loss_per_contract = (strike_width - credit_received) * 100
        elif strategy_type == "IRON_BUTTERFLY":
            max_loss_per_contract = (strike_width - credit_received) * 100
        elif strategy_type == "PUT_CREDIT_SPREAD" or strategy_type == "CALL_CREDIT_SPREAD":
            max_loss_per_contract = (strike_width - credit_received) * 100
        elif strategy_type == "DIAGONAL":
            # Conservative: use full debit as max risk
            max_loss_per_contract = credit_received * 100
        else:
            max_loss_per_contract = 1000  # fallback
        if max_loss_per_contract <= 0:
            max_loss_per_contract = 1  # avoid division by zero
        contracts_by_risk = math.floor(max_risk_per_trade / max_loss_per_contract)
        # Optionally, cap by available buying power (if available)
        # For now, just use contracts_by_risk
        contracts = max(1, contracts_by_risk)
        print(f"[Sizing] {strategy_type}: Portfolio=${portfolio_value:.2f}, MaxRisk/Trade=${max_risk_per_trade:.2f}, MaxLoss/Contract=${max_loss_per_contract:.2f}, Contracts={contracts}")
        return contracts

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
        # Placeholder: select strikes and get quotes
        short_put_strike = 440
        long_put_strike = 435
        short_call_strike = 460
        long_call_strike = 465
        short_put_credit = 1.20
        long_put_debit = 0.60
        short_call_credit = 1.10
        long_call_debit = 0.55
        credit_received = (short_put_credit + short_call_credit) - (long_put_debit + long_call_debit)
        strike_width = abs(short_put_strike - long_put_strike)
        print(f"[DEBUG] Iron Condor: strike_width={strike_width}, credit_received={credit_received}")
        account = self.trading_client.get_account()
        equity = getattr(account, 'equity', None)
        try:
            portfolio_value = float(equity) if equity is not None else 25000.0
        except Exception:
            portfolio_value = 25000.0
        contracts = self.calculate_position_size(portfolio_value, "IRON_CONDOR", strike_width, credit_received)
        print(f"[DEBUG] Iron Condor contracts to trade: {contracts}")
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
        # Placeholder: select strikes and get quotes
        long_call_strike = 450
        short_call_strike = 455
        long_call_debit = 4.50
        short_call_credit = 1.20
        credit_received = long_call_debit - short_call_credit  # net debit
        strike_width = abs(long_call_strike - short_call_strike)
        print(f"[DEBUG] Diagonal: strike_width={strike_width}, credit_received={credit_received}")
        account = self.trading_client.get_account()
        equity = getattr(account, 'equity', None)
        try:
            portfolio_value = float(equity) if equity is not None else 25000.0
        except Exception:
            portfolio_value = 25000.0
        contracts = self.calculate_position_size(portfolio_value, "DIAGONAL", strike_width, credit_received)
        print(f"[DEBUG] Diagonal contracts to trade: {contracts}")
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
            print("[Diagonal] Expiry0 used:", expiry0)
            print("[Diagonal] Total contracts returned (0DTE):", len(calls0))
            print("[Diagonal] Call strikes (0DTE):", sorted(set(c.strike_price for c in calls0)))
            print("[Diagonal] Expiry7 used:", expiry7)
            print("[Diagonal] Total contracts returned (7DTE):", len(calls7))
            print("[Diagonal] Call strikes (7DTE):", sorted(set(c.strike_price for c in calls7)))
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
            print("[Call Credit Spread] Expiry used:", expiry)
            print("[Call Credit Spread] Total contracts returned:", len(option_contracts))
            print("[Call Credit Spread] Types found:", set(c.type for c in option_contracts))
            print("[Call Credit Spread] First 5 contracts:")
            for c in option_contracts[:5]:
                print(vars(c))
            calls = [c for c in option_contracts if c.type == 'call']
            print("[Call Credit Spread] Call strikes:", sorted(set(c.strike_price for c in calls)))
            calls.sort(key=lambda c: abs(c.strike_price - spy_price))
            short_call = next((c for c in calls if c.strike_price >= spy_price), None)
            if not short_call:
                return False, "No suitable short call found"
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
            all_strikes = sorted(set([c.strike_price for c in calls] + [p.strike_price for p in puts]), key=lambda x: abs(x - spy_price))
            if not all_strikes:
                return False, "No strikes found"
            atm_strike = all_strikes[0]
            print("Available call strikes:", sorted([c.strike_price for c in calls]))
            print("Available put strikes:", sorted([p.strike_price for p in puts]))
            print("ATM strike selected:", atm_strike)
            short_call = next((c for c in calls if abs(c.strike_price - atm_strike) <= 0.05), None)
            short_put = next((p for p in puts if abs(p.strike_price - atm_strike) <= 0.05), None)
            if not short_call or not short_put:
                return False, "No suitable ATM call/put found"
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
            print("[Put Credit Spread] Expiry used:", expiry)
            print("[Put Credit Spread] Total contracts returned:", len(option_contracts))
            print("[Put Credit Spread] Types found:", set(c.type for c in option_contracts))
            print("[Put Credit Spread] First 5 contracts:")
            for c in option_contracts[:5]:
                print(vars(c))
            puts = [c for c in option_contracts if c.type == 'put']
            print("[Put Credit Spread] Put strikes:", sorted(set(p.strike_price for p in puts)))
            puts.sort(key=lambda p: abs(p.strike_price - spy_price))
            short_put = next((p for p in puts if p.strike_price <= spy_price), None)
            if not short_put:
                return False, "No suitable short put found"
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
        while True:
            now = datetime.now()
            today = now.date()
            if self.last_trade_date != today:
                print(f"[RiskManager] New trading day: {today}. Resetting counters.")
                self.risk_manager.reset_daily_counters()
                self.last_trade_date = today

            # Get portfolio value
            account = self.trading_client.get_account()
            portfolio_value = None
            equity = getattr(account, 'equity', None)
            try:
                if equity is not None:
                    portfolio_value = float(equity)
            except Exception:
                portfolio_value = None
            if portfolio_value is None:
                print("[RiskManager] Could not get portfolio value from account. Retrying in 5 minutes.")
                await asyncio.sleep(60 * 5)
                continue

            # Check if we can trade
            if not self.risk_manager.can_trade(portfolio_value):
                print("[RiskManager] Trading halted for today due to risk limits.")
                await asyncio.sleep(60 * 5)  # Wait 5 minutes before checking again
                continue

            # Check and manage open positions for profit/stop-loss
            await self.check_and_manage_positions()

            print(f"Portfolio value: ${portfolio_value:,.2f}")
            strategy, conditions = await self.analyze_market_conditions()
            if strategy == "NO_TRADE":
                print("No trading conditions met today")
                await asyncio.sleep(60 * 5)  # 5 minutes between checks
                continue

            spy_price = await self.get_spy_price()
            if not spy_price:
                print("Could not get SPY price")
                await asyncio.sleep(60 * 5)  # 5 minutes between checks
                continue

            # --- DYNAMIC SIZING ---
            # Example: extract strike_width and credit_received from selected contracts
            # For now, use placeholders; replace with real contract selection logic
            strike_width = 5  # TODO: set from selected contracts
            credit_received = 1.0  # TODO: set from selected contracts
            if strategy in ["IRON_CONDOR", "IRON_BUTTERFLY", "PUT_CREDIT_SPREAD", "CALL_CREDIT_SPREAD", "DIAGONAL"]:
                # Insert logic to select contracts and calculate strike_width and credit_received
                # Example for credit spread:
                # strike_width = abs(short_strike - long_strike)
                # credit_received = net_credit (per contract)
                print(f"[DEBUG] Sizing inputs for {strategy}: strike_width={strike_width}, credit_received={credit_received}")
                contracts = self.calculate_position_size(portfolio_value, strategy, strike_width, credit_received)
            else:
                contracts = 1
            print(f"Position size: {contracts} contracts")

            if strategy == "IRON_CONDOR":
                success, message = await self.execute_iron_condor(spy_price, None)
            elif strategy == "DIAGONAL":
                success, message = await self.execute_diagonal(spy_price, None)
            elif strategy == "PUT_CREDIT_SPREAD":
                success, message = await self.execute_put_credit_spread(spy_price, contracts)
            elif strategy == "CALL_CREDIT_SPREAD":
                success, message = await self.execute_call_credit_spread(spy_price, contracts)
            elif strategy == "IRON_BUTTERFLY":
                success, message = await self.execute_iron_butterfly(spy_price, contracts)
            print(f"Execution result: {success} - {message}")

            # After placing a trade:
            self.risk_manager.trades_today += 1
            print(f"[RiskManager] Trade placed. Trades today: {self.risk_manager.trades_today}")

            # After closing a position, update daily_pnl:
            # Example: realized_pnl = ...
            # self.risk_manager.daily_pnl += realized_pnl
            # print(f"[RiskManager] Updated daily P&L: {self.risk_manager.daily_pnl}")

            # Check and manage open positions for profit/stop-loss
            await self.check_and_manage_positions()

            # Sleep or wait for next opportunity
            await asyncio.sleep(60 * 5)  # 5 minutes between checks

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