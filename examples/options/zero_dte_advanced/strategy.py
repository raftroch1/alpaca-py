from dotenv import load_dotenv
import os
# Robustly find and load .env from the project root (where .env.example is)
def find_project_root_with_env(start_path):
    current = os.path.abspath(start_path)
    while not os.path.exists(os.path.join(current, '.env')) and current != os.path.dirname(current):
        current = os.path.dirname(current)
    return current

project_root = find_project_root_with_env(__file__)
dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=dotenv_path)

import pandas as pd  # type: ignore
import numpy as np  # type: ignore
import talib  # type: ignore
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import asyncio
import logging
from dataclasses import dataclass, field
import yfinance as yf
import time
import traceback

from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient, OptionHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, OptionChainRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

@dataclass
class StrategyConfig:
    """Configuration for the 0DTE SPY strategy"""
    max_position_size: float = 10000
    max_daily_loss: float = 2500
    profit_target: float = 0.30
    stop_loss: float = 0.50
    fast_ema: int = 5
    slow_ema: int = 13
    volume_ma_period: int = 20
    atr_period: int = 14
    rsi_period: int = 14
    vwap_periods: List[int] = field(default_factory=lambda: [5, 15, 30, 60])
    dte_filter: int = 0
    delta_range: Tuple[float, float] = (0.15, 0.35)
    min_volume: int = 100
    max_spread_pct: float = 0.05
    market_open_buffer: int = 30
    market_close_buffer: int = 30

class TechnicalIndicators:
    @staticmethod
    def anchored_vwap(df: pd.DataFrame, anchor_points: List[int]) -> Dict[str, pd.Series]:
        vwaps = {}
        for i, anchor in enumerate(anchor_points):
            if anchor < len(df):
                anchor_data = df.iloc[anchor:].copy()
                typical_price = (anchor_data['high'] + anchor_data['low'] + anchor_data['close']) / 3
                volume_price = typical_price * anchor_data['volume']
                cum_volume_price = volume_price.cumsum()
                cum_volume = anchor_data['volume'].cumsum()
                vwaps[f'avwap_{i}'] = cum_volume_price / cum_volume
        return vwaps
    @staticmethod
    def volume_profile(df: pd.DataFrame, bins: int = 50) -> Dict:
        price_range = df['high'].max() - df['low'].min()
        bin_size = price_range / bins
        profile = {}
        for _, row in df.iterrows():
            price_levels = np.arange(row['low'], row['high'] + bin_size, bin_size)
            volume_per_level = row['volume'] / len(price_levels)
            for level in price_levels:
                rounded_level = round(level, 2)
                if rounded_level not in profile:
                    profile[rounded_level] = 0
                profile[rounded_level] += volume_per_level
        sorted_profile = sorted(profile.items(), key=lambda x: x[1], reverse=True)
        poc_price = sorted_profile[0][0]
        total_volume = sum(profile.values())
        value_area_volume = 0
        value_area_prices = []
        for price, volume in sorted_profile:
            value_area_volume += volume
            value_area_prices.append(price)
            if value_area_volume >= total_volume * 0.70:
                break
        return {
            'poc': poc_price,
            'value_area_high': max(value_area_prices),
            'value_area_low': min(value_area_prices),
            'profile': profile
        }
    @staticmethod
    def momentum_confluence(df: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
        df['ema_fast'] = talib.EMA(df['close'], timeperiod=config.fast_ema)
        df['ema_slow'] = talib.EMA(df['close'], timeperiod=config.slow_ema)
        df['ema_cross'] = np.where(df['ema_fast'] > df['ema_slow'], 1, -1)
        df['ema_cross_signal'] = df['ema_cross'].diff()
        df['macd'], df['macd_signal'], df['macd_hist'] = talib.MACD(df['close'])
        df['macd_cross'] = np.where(df['macd'] > df['macd_signal'], 1, -1)
        df['macd_cross_signal'] = df['macd_cross'].diff()
        df['rsi'] = talib.RSI(df['close'], timeperiod=config.rsi_period)
        df['rsi_oversold'] = df['rsi'] < 30
        df['rsi_overbought'] = df['rsi'] > 70
        df['atr'] = talib.ATR(df['high'], df['low'], df['close'], timeperiod=config.atr_period)
        df['atr_pct'] = (df['atr'] / df['close']) * 100
        df['volume_ma'] = df['volume'].rolling(config.volume_ma_period).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        df['high_volume'] = df['volume_ratio'] > 1.5
        df['higher_high'] = (df['high'] > df['high'].shift(1)) & (df['high'].shift(1) > df['high'].shift(2))
        df['lower_low'] = (df['low'] < df['low'].shift(1)) & (df['low'].shift(1) < df['low'].shift(2))
        return df

class OptionsAnalyzer:
    def __init__(self, option_client: OptionHistoricalDataClient):
        self.option_client = option_client
    def get_option_chain_analysis(self, symbol: str, expiry: str) -> Dict:
        request = OptionChainRequest(
            underlying_symbol=symbol,
            expiration_date=expiry
        )
        chain = self.option_client.get_option_chain(request)
        analysis = {
            'high_volume_strikes': [],
            'gamma_risk_zones': [],
            'pin_risk_levels': [],
            'liquidity_scores': {}
        }
        for option in chain:
            # Defensive: skip if option is not the expected object (e.g., string, RawData, etc.)
            if not hasattr(option, 'volume') or not hasattr(option, 'strike_price'):
                continue
            if getattr(option, 'volume', 0) > 100:
                analysis['high_volume_strikes'].append({
                    'strike': getattr(option, 'strike_price', None),
                    'type': getattr(option, 'option_type', None),
                    'volume': getattr(option, 'volume', None),
                    'open_interest': getattr(option, 'open_interest', None),
                    'delta': getattr(getattr(option, 'greeks', None), 'delta', None)
                })
        return analysis
    def calculate_position_sizing(self, entry_price: float, stop_loss: float, max_risk: float) -> int:
        risk_per_contract = abs(entry_price - stop_loss) * 100
        if risk_per_contract == 0:
            return 0
        return int(max_risk / risk_per_contract)

class MarketRegimeDetector:
    @staticmethod
    def detect_regime(df: pd.DataFrame, lookback: int = 20) -> str:
        recent_data = df.tail(lookback)
        volatility = recent_data['atr_pct'].mean()
        trend_strength = abs(recent_data['ema_fast'].iloc[-1] - recent_data['ema_slow'].iloc[-1]) / recent_data['close'].iloc[-1]
        volume_trend = recent_data['volume_ratio'].mean()
        if volatility > 2.0 and volume_trend > 1.3:
            return "high_volatility"
        elif trend_strength > 0.02 and volume_trend > 1.1:
            return "trending"
        elif volatility < 1.0 and volume_trend < 0.8:
            return "low_volatility"
        else:
            return "neutral"

class ZeroDTEStrategy:
    def __init__(self, api_key: str, secret_key: str, config: StrategyConfig):
        self.trading_client = TradingClient(api_key, secret_key, paper=True, url_override=os.getenv("ALPACA_API_BASE_URL", "https://paper-api.alpaca.markets/v2"))
        self.stock_client = StockHistoricalDataClient(api_key, secret_key)
        self.option_client = OptionHistoricalDataClient(api_key, secret_key, url_override=os.getenv("ALPACA_API_BASE_URL", "https://paper-api.alpaca.markets/v2"))
        self.config = config
        self.options_analyzer = OptionsAnalyzer(self.option_client)
        self.current_positions = {}
        self.daily_pnl = 0.0
        self.trade_count = 0
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[
                logging.FileHandler("strategy.log"),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    def get_market_data(self, symbol: str = "SPY", timeframe: Optional[TimeFrame] = None) -> pd.DataFrame:
        if timeframe is None:
            # TimeFrame.Minute is a classproperty returning a TimeFrame instance
            timeframe = TimeFrame.Minute  # type: ignore
        end_time = datetime.now()
        start_time = end_time - timedelta(days=5)
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=timeframe,  # type: ignore
            start=start_time,
            end=end_time
        )
        bars = self.stock_client.get_stock_bars(request)
        if not hasattr(bars, 'df'):
            raise RuntimeError("Alpaca SDK did not return a DataFrame. Check your API response.")
        df = bars.df.reset_index()  # type: ignore[attr-defined]
        df = TechnicalIndicators.momentum_confluence(df, self.config)
        df['vwap'] = (df['volume'] * (df['high'] + df['low'] + df['close']) / 3).cumsum() / df['volume'].cumsum()
        pivot_points = self.find_pivot_points(df)
        anchored_vwaps = TechnicalIndicators.anchored_vwap(df, pivot_points)
        for name, vwap_series in anchored_vwaps.items():
            df[name] = vwap_series
        return df
    def find_pivot_points(self, df: pd.DataFrame, window: int = 10) -> List[int]:
        highs = df['high'].rolling(window, center=True).max()
        lows = df['low'].rolling(window, center=True).min()
        pivot_highs = df.index[(df['high'] == highs) & (df['high'] > df['high'].shift(1)) & (df['high'] > df['high'].shift(-1))].tolist()
        pivot_lows = df.index[(df['low'] == lows) & (df['low'] < df['low'].shift(1)) & (df['low'].shift(1) < df['low'].shift(2))].tolist()
        return sorted(pivot_highs + pivot_lows)[-5:]
    def generate_signals(self, df: pd.DataFrame) -> Dict:
        current_idx = len(df) - 1
        current_bar = df.iloc[current_idx]
        signals = {
            'direction': None,
            'strength': 0,
            'entry_reasons': [],
            'risk_level': 'medium'
        }
        if current_bar['ema_cross_signal'] == 2:
            signals['direction'] = 'bullish'
            signals['strength'] += 2
            signals['entry_reasons'].append('EMA bullish crossover')
        elif current_bar['ema_cross_signal'] == -2:
            signals['direction'] = 'bearish'
            signals['strength'] += 2
            signals['entry_reasons'].append('EMA bearish crossover')
        if current_bar['macd_cross_signal'] == 2 and signals['direction'] == 'bullish':
            signals['strength'] += 1
            signals['entry_reasons'].append('MACD bullish confirmation')
        elif current_bar['macd_cross_signal'] == -2 and signals['direction'] == 'bearish':
            signals['strength'] += 1
            signals['entry_reasons'].append('MACD bearish confirmation')
        if current_bar['high_volume']:
            signals['strength'] += 1
            signals['entry_reasons'].append('High volume confirmation')
        close_price = current_bar['close']
        vwap_price = current_bar['vwap']
        if close_price > vwap_price and signals['direction'] == 'bullish':
            signals['strength'] += 1
            signals['entry_reasons'].append('Above VWAP support')
        elif close_price < vwap_price and signals['direction'] == 'bearish':
            signals['strength'] += 1
            signals['entry_reasons'].append('Below VWAP resistance')
        if current_bar['atr_pct'] > 2.5:
            signals['risk_level'] = 'high'
        elif current_bar['atr_pct'] < 1.0:
            signals['risk_level'] = 'low'
        regime = MarketRegimeDetector.detect_regime(df)
        if regime == 'high_volatility':
            signals['strength'] -= 1
        elif regime == 'trending':
            signals['strength'] += 1
        return signals
    def find_optimal_strikes(self, current_price: float, direction: str, expiry: str) -> List[Dict]:
        strikes = []
        if direction == 'bullish':
            for delta_target in np.arange(self.config.delta_range[0], self.config.delta_range[1], 0.05):
                estimated_strike = current_price * (1 + (0.5 - delta_target) * 0.1)
                strikes.append({
                    'strike': round(estimated_strike, 0),
                    'type': 'call',
                    'target_delta': delta_target
                })
        else:
            for delta_target in np.arange(-self.config.delta_range[1], -self.config.delta_range[0], 0.05):
                estimated_strike = current_price * (1 - (0.5 + delta_target) * 0.1)
                strikes.append({
                    'strike': round(estimated_strike, 0),
                    'type': 'put',
                    'target_delta': delta_target
                })
        return strikes
    def execute_trade(self, signal: Dict, current_price: float) -> bool:
        if signal['strength'] < 3:
            return False
        if self.daily_pnl <= -self.config.max_daily_loss:
            self.logger.warning("Daily loss limit reached. No new trades.")
            return False
        today = datetime.now().strftime('%Y-%m-%d')
        strikes = self.find_optimal_strikes(current_price, signal['direction'], today)
        if not strikes:
            return False
        selected_strike = strikes[0]
        risk_amount = self.config.max_position_size * 0.1
        estimated_option_price = current_price * 0.02
        position_size = self.options_analyzer.calculate_position_sizing(
            estimated_option_price, 
            estimated_option_price * (1 - self.config.stop_loss),
            risk_amount
        )
        exp_str = datetime.now().strftime('%y%m%d')
        option_type = 'C' if selected_strike['type'] == 'call' else 'P'
        strike_str = f"{int(selected_strike['strike'] * 1000):08d}"
        option_symbol = f"SPY{exp_str}{option_type}{strike_str}"
        try:
            order_request = MarketOrderRequest(
                symbol=option_symbol,
                qty=position_size,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY
            )
            order = self.trading_client.submit_order(order_request)
            # Defensive: check if order has 'id' attribute
            order_id = getattr(order, 'id', None)
            if order_id is None:
                self.logger.error("Order object does not have an 'id' attribute. Skipping position tracking.")
                return False
            self.current_positions[order_id] = {
                'entry_price': estimated_option_price,
                'quantity': position_size,
                'direction': signal['direction'],
                'entry_time': datetime.now(),
                'stop_loss': estimated_option_price * (1 - self.config.stop_loss),
                'profit_target': estimated_option_price * (1 + self.config.profit_target)
            }
            self.logger.info(f"Trade executed: {option_symbol}, Qty: {position_size}, "
                           f"Direction: {signal['direction']}, Reasons: {signal['entry_reasons']}")
            return True
        except Exception as e:
            self.logger.error(f"Trade execution failed: {e}")
            return False
    def manage_positions(self):
        for position_id, position in list(self.current_positions.items()):
            current_price = position['entry_price'] * np.random.uniform(0.8, 1.2)
            if current_price <= position['stop_loss']:
                self.close_position(position_id, current_price, 'stop_loss')
            elif current_price >= position['profit_target']:
                self.close_position(position_id, current_price, 'profit_target')
            elif datetime.now().hour == 15 and datetime.now().minute >= 45:
                self.close_position(position_id, current_price, 'time_exit')
    def close_position(self, position_id: str, exit_price: float, reason: str):
        position = self.current_positions[position_id]
        pnl = (exit_price - position['entry_price']) * position['quantity'] * 100
        self.daily_pnl += pnl
        self.logger.info(f"Position closed: {position_id}, P&L: ${pnl:.2f}, Reason: {reason}")
        del self.current_positions[position_id]
    async def run_strategy(self):
        self.logger.info("Starting 0DTE SPY Strategy")
        while True:
            try:
                self.logger.info("Checking market hours...")
                now = datetime.now()
                if not (9 <= now.hour <= 15):
                    self.logger.info("Market is closed. Waiting...")
                    await asyncio.sleep(60)
                    continue
                self.logger.info("Fetching market data...")
                df = self.get_market_data()
                self.logger.info("Generating signals...")
                signals = self.generate_signals(df)
                self.logger.info("Checking for trade opportunities...")
                current_price = df.iloc[-1]['close']
                if signals['direction'] and signals['strength'] >= 3:
                    self.logger.info("Executing trade...")
                    self.execute_trade(signals, current_price)
                else:
                    self.logger.info("No trade signal this cycle.")
                self.logger.info("Managing positions...")
                self.manage_positions()
                self.logger.info("Sleeping for 30 seconds...")
                await asyncio.sleep(30)
            except Exception as e:
                self.logger.error(f"Strategy error: {e}\n{traceback.format_exc()}")
                await asyncio.sleep(60)

    async def get_current_vix(self):
        """Get current VIX level from Yahoo Finance"""
        try:
            vix = yf.Ticker("^VIX")
            hist = vix.history(period="5d")
            if len(hist) >= 2:
                current_vix = hist['Close'].iloc[-1]
                return current_vix
            else:
                print("VIX history data is too short:", hist)
                return None
        except Exception as e:
            print(f"Error getting VIX data from Yahoo Finance: {e}")
            return None

async def main():
    strategy = ZeroDTEStrategy(
        api_key=os.getenv("ALPACA_API_KEY"),
        secret_key=os.getenv("ALPACA_SECRET_KEY"),
        config=StrategyConfig(
            max_position_size=5000,
            max_daily_loss=1000,
            profit_target=0.25,
            stop_loss=0.40
        )
    )
    await strategy.run_strategy()

if __name__ == "__main__":
    asyncio.run(main()) 