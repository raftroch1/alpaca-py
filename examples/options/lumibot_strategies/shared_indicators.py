import numpy as np
import talib
import pandas as pd

class TechnicalIndicators:
    @staticmethod
    def momentum_confluence(df: pd.DataFrame, config) -> pd.DataFrame:
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