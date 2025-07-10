# Realistic SPY Options Backtest using Alpaca OptionHistoricalDataClient
# Implements all regime-mapped strategies from reenhanced_multi_regime_options_strategy.py
# Simulates 0DTE, premium-selling, risk-managed trading for the last month

import os
import csv
from datetime import datetime, timedelta
from alpaca.data.historical import OptionHistoricalDataClient, StockHistoricalDataClient
from alpaca.data.requests import OptionChainRequest, OptionBarsRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame
import numpy as np
import pandas as pd
import yfinance as yf

# Load .env if present (same logic as multi_regime_backtest.py)
try:
    from dotenv import load_dotenv
    def find_project_root_with_env(start_path):
        current = os.path.abspath(start_path)
        while not os.path.exists(os.path.join(current, '.env')) and current != os.path.dirname(current):
            current = os.path.dirname(current)
        return current
    project_root = find_project_root_with_env(__file__)
    dotenv_path = os.path.join(project_root, '.env')
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path=dotenv_path)
except ImportError:
    pass

API_KEY = os.getenv('ALPACA_API_KEY')
SECRET_KEY = os.getenv('ALPACA_SECRET_KEY')
START_CASH = 25000
MAX_TRADES_PER_DAY = 3
MAX_RISK_PER_TRADE = 0.02
MAX_DAILY_LOSS = 0.03
KELLY_FRACTION = 0.25
LOG_FILE = 'spy_options_realistic_pnl_log.csv'

LOW_VOL_THRESHOLD = 17
HIGH_VOL_THRESHOLD = 18

REGIME_TO_STRATEGY = {
    'HIGH_VOL': 'IRON_CONDOR',
    'LOW_VOL': 'DIAGONAL',
    'MODERATE_BULL': 'PUT_CREDIT_SPREAD',
    'MODERATE_BEAR': 'CALL_CREDIT_SPREAD',
    'MODERATE_FLAT': 'IRON_BUTTERFLY',
    'NO_TRADE': None
}

def occ_option_symbol(underlying, expiry, opt_type, strike):
    # expiry: YYYY-MM-DD, opt_type: 'call' or 'put', strike: float
    dt = datetime.strptime(expiry, '%Y-%m-%d')
    y = str(dt.year)[-2:]
    m = f"{dt.month:02d}"
    d = f"{dt.day:02d}"
    t = 'C' if opt_type == 'call' else 'P'
    strike_int = int(strike * 1000)
    strike_str = f"{strike_int:08d}"
    return f"{underlying}{y}{m}{d}{t}{strike_str}"

def get_spy_open_price(stock_client, day):
    # Try Alpaca first
    try:
        bars = stock_client.get_stock_bars(StockBarsRequest(symbol_or_symbols=['SPY'], timeframe=TimeFrame.Minute, start=day, end=day+timedelta(days=1)))
        if bars and 'SPY' in bars and len(bars['SPY']) > 0:
            return bars['SPY'][0].open
    except Exception as e:
        print(f"[WARN] Alpaca SPY bars fetch failed: {e}")
    # Fallback to yfinance
    try:
        spy_df = yf.download('SPY', start=day.strftime('%Y-%m-%d'), end=(day+timedelta(days=1)).strftime('%Y-%m-%d'), progress=False, interval='1m')
        if not spy_df.empty and 'Open' in spy_df.columns:
            return float(spy_df.iloc[0]['Open'])
    except Exception as e:
        print(f"[WARN] yfinance SPY bars fetch failed: {e}")
    print(f"[SKIP] No SPY open price for {day.date()}")
    return None

def get_option_open_close(option_client, symbol, day):
    try:
        bars_req = OptionBarsRequest(symbol_or_symbols=[symbol], timeframe=TimeFrame.Minute, start=day, end=day+timedelta(days=1))
        bars = option_client.get_option_bars(bars_req)
        if not bars or symbol not in bars or len(bars[symbol]) < 2:
            print(f"[SKIP] No option bars for {symbol} on {day.date()}")
            return None, None
        return bars[symbol][0].open, bars[symbol][-1].close
    except Exception as e:
        print(f"[SKIP] Option bars fetch failed for {symbol} on {day.date()}: {e}")
        return None, None

# NOTE: This script is now reverted to use SPY as the underlying, for full Alpaca data access.
# All logic previously using AAPL now uses SPY.
def main():
    option_client = OptionHistoricalDataClient(api_key=API_KEY, secret_key=SECRET_KEY)
    stock_client = StockHistoricalDataClient(api_key=API_KEY, secret_key=SECRET_KEY)
    # Set backtest range: past 3 months ending on 2025-06-30
    end = datetime(2025, 6, 30)
    start = end - timedelta(days=90)
    print(f"Backtest from {start.date()} to {end.date()}")
    trading_days = pd.bdate_range(start=start, end=end).to_pydatetime().tolist()
    cash = START_CASH
    with open(LOG_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['date', 'strategy', 'contracts', 'entry_premium', 'exit_premium', 'pnl', 'regime', 'legs'])
    for day in trading_days:
        print(f"\n=== {day.date()} ===")
        # 1. Get VIX for regime selection using yfinance
        vix_day_str = day.strftime('%Y-%m-%d')
        vix_next_day_str = (day + timedelta(days=1)).strftime('%Y-%m-%d')
        try:
            vix_df = yf.download('^VIX', start=vix_day_str, end=vix_next_day_str, progress=False)
            if vix_df.empty or 'Open' not in vix_df.columns or 'Close' not in vix_df.columns:
                print(f"[SKIP] No VIX data from yfinance for {day.date()}")
                continue
            vix_open = float(vix_df['Open'].iloc[0])
            vix_close = float(vix_df['Close'].iloc[0])
        except Exception as e:
            print(f"[SKIP] Error fetching VIX from yfinance for {day.date()}: {e}")
            continue
        vix_prev = vix_open
        vix_today = vix_close
        print(f"VIX: open={vix_open}, close={vix_close}")
        # 2. Determine regime
        if vix_today > vix_prev and vix_today > HIGH_VOL_THRESHOLD:
            regime = 'HIGH_VOL'
        elif vix_today < LOW_VOL_THRESHOLD:
            regime = 'LOW_VOL'
        elif LOW_VOL_THRESHOLD <= vix_today <= HIGH_VOL_THRESHOLD:
            regime = 'MODERATE_FLAT'
        else:
            regime = 'NO_TRADE'
        strategy = REGIME_TO_STRATEGY.get(regime)
        print(f"Regime: {regime} | Strategy: {strategy}")
        if not strategy:
            print(f"[SKIP] No strategy for regime {regime} on {day.date()}")
            continue
        # 3. Get SPY open price for the day using Alpaca daily bars
        try:
            spy_bars = stock_client.get_stock_bars(StockBarsRequest(
                symbol_or_symbols=['SPY'],
                timeframe=TimeFrame.Day,
                start=day,
                end=day + timedelta(days=1)
            ))
            if not spy_bars or 'SPY' not in spy_bars or len(spy_bars['SPY']) == 0:
                print(f"[SKIP] No SPY open price for {day.date()}")
                continue
            spy_open = spy_bars['SPY'][0].open
            print(f"SPY open: {spy_open}")
        except Exception as e:
            print(f"[SKIP] Error fetching SPY open price for {day.date()}: {e}")
            continue
        # 4. Get SPY option chain for the day
        try:
            chain_req = OptionChainRequest(underlying_symbol='SPY', as_of=day)
            chain = option_client.get_option_chain(chain_req)
        except Exception as e:
            print(f"[SKIP] Option chain fetch failed for {day.date()}: {e}")
            continue
        if not chain:
            print(f"[SKIP] No option chain for {day.date()}")
            continue
        # Use direct attribute access for OptionsSnapshot
        expiries = sorted(set(c.expiration_date for c in chain.values()))
        if not expiries:
            print(f"[SKIP] No expiries in option chain for {day.date()}")
            continue
        print(f"Option expiries: {expiries}")
        expiry_0dte = min(expiries, key=lambda x: abs((datetime.strptime(x, '%Y-%m-%d').date() - day.date()).days))
        expiry_7dte = None
        for e in expiries:
            if (datetime.strptime(e, '%Y-%m-%d').date() - day.date()).days == 7:
                expiry_7dte = e
                break
        print(f"Using expiry_0dte: {expiry_0dte}, expiry_7dte: {expiry_7dte}")
        daily_pnl = 0
        trades_today = 0
        for trade_num in range(MAX_TRADES_PER_DAY):
            print(f"Trade {trade_num+1} for {day.date()} | Strategy: {strategy}")
            legs = []
            entry_premium = 0
            exit_premium = 0
            contracts_to_trade = 1
            skip_reason = None
            if strategy == 'IRON_CONDOR':
                calls = [c for c in chain.values() if c.expiration_date == expiry_0dte and c.type == 'call']
                puts = [c for c in chain.values() if c.expiration_date == expiry_0dte and c.type == 'put']
                call_strikes = sorted([c.strike_price for c in calls])
                put_strikes = sorted([p.strike_price for p in puts])
                atm_call_strike = min(call_strikes, key=lambda x: abs(x - spy_open)) if call_strikes else None
                atm_put_strike = min(put_strikes, key=lambda x: abs(x - spy_open)) if put_strikes else None
                otm_call_strike = min([s for s in call_strikes if s > atm_call_strike], default=None) if atm_call_strike else None
                otm_put_strike = max([s for s in put_strikes if s < atm_put_strike], default=None) if atm_put_strike else None
                if None in [atm_call_strike, atm_put_strike, otm_call_strike, otm_put_strike]:
                    skip_reason = 'No suitable strikes for iron condor'
                short_call = next((c for c in calls if c.strike_price == atm_call_strike), None)
                long_call = next((c for c in calls if c.strike_price == otm_call_strike), None)
                short_put = next((p for p in puts if p.strike_price == atm_put_strike), None)
                long_put = next((p for p in puts if p.strike_price == otm_put_strike), None)
                if None in [short_call, long_call, short_put, long_put]:
                    skip_reason = 'No suitable contracts for iron condor'
                legs_info = []
                for leg, side in zip([short_call, long_call, short_put, long_put], ['sell', 'buy', 'sell', 'buy']):
                    if leg is None:
                        break
                    symbol = occ_option_symbol('SPY', expiry_0dte, leg.type, leg.strike_price)
                    open_px, close_px = get_option_open_close(option_client, symbol, day)
                    if open_px is None or close_px is None:
                        break
                    legs_info.append({'symbol': symbol, 'side': side, 'open': open_px, 'close': close_px})
                if len(legs_info) != 4:
                    skip_reason = 'Missing open/close prices for iron condor legs'
                entry_premium = sum(l['open'] if l['side']=='sell' else -l['open'] for l in legs_info)
                exit_premium = sum(l['close'] if l['side']=='sell' else -l['close'] for l in legs_info)
                legs = legs_info
            elif strategy == 'DIAGONAL' and expiry_7dte:
                calls_0dte = [c for c in chain.values() if c.expiration_date == expiry_0dte and c.type == 'call']
                calls_7dte = [c for c in chain.values() if c.expiration_date == expiry_7dte and c.type == 'call']
                call_strikes_0dte = sorted([c.strike_price for c in calls_0dte])
                call_strikes_7dte = sorted([c.strike_price for c in calls_7dte])
                atm_strike_0dte = min(call_strikes_0dte, key=lambda x: abs(x - spy_open)) if call_strikes_0dte else None
                atm_strike_7dte = min(call_strikes_7dte, key=lambda x: abs(x - spy_open)) if call_strikes_7dte else None
                short_call = next((c for c in calls_0dte if c.strike_price == atm_strike_0dte), None)
                long_call = next((c for c in calls_7dte if c.strike_price == atm_strike_7dte), None)
                if None in [short_call, long_call]:
                    skip_reason = 'No suitable contracts for diagonal'
                legs_info = []
                for leg, side, expiry in zip([long_call, short_call], ['buy', 'sell'], [expiry_7dte, expiry_0dte]):
                    if leg is None:
                        break
                    symbol = occ_option_symbol('SPY', expiry, 'call', leg.strike_price)
                    open_px, close_px = get_option_open_close(option_client, symbol, day)
                    if open_px is None or close_px is None:
                        break
                    legs_info.append({'symbol': symbol, 'side': side, 'open': open_px, 'close': close_px})
                if len(legs_info) != 2:
                    skip_reason = 'Missing open/close prices for diagonal legs'
                entry_premium = sum(l['open'] if l['side']=='sell' else -l['open'] for l in legs_info)
                exit_premium = sum(l['close'] if l['side']=='sell' else -l['close'] for l in legs_info)
                legs = legs_info
            elif strategy == 'PUT_CREDIT_SPREAD':
                puts = [c for c in chain.values() if c.expiration_date == expiry_0dte and c.type == 'put']
                put_strikes = sorted([p.strike_price for p in puts])
                atm_put_strike = min(put_strikes, key=lambda x: abs(x - spy_open)) if put_strikes else None
                lower_put_strike = max([s for s in put_strikes if s < atm_put_strike], default=None) if atm_put_strike else None
                if None in [atm_put_strike, lower_put_strike]:
                    skip_reason = 'No suitable strikes for put credit spread'
                short_put = next((p for p in puts if p.strike_price == atm_put_strike), None)
                long_put = next((p for p in puts if p.strike_price == lower_put_strike), None)
                if None in [short_put, long_put]:
                    skip_reason = 'No suitable contracts for put credit spread'
                legs_info = []
                for leg, side in zip([short_put, long_put], ['sell', 'buy']):
                    if leg is None:
                        break
                    symbol = occ_option_symbol('SPY', expiry_0dte, 'put', leg.strike_price)
                    open_px, close_px = get_option_open_close(option_client, symbol, day)
                    if open_px is None or close_px is None:
                        break
                    legs_info.append({'symbol': symbol, 'side': side, 'open': open_px, 'close': close_px})
                if len(legs_info) != 2:
                    skip_reason = 'Missing open/close prices for put credit spread legs'
                entry_premium = sum(l['open'] if l['side']=='sell' else -l['open'] for l in legs_info)
                exit_premium = sum(l['close'] if l['side']=='sell' else -l['close'] for l in legs_info)
                legs = legs_info
            elif strategy == 'CALL_CREDIT_SPREAD':
                calls = [c for c in chain.values() if c.expiration_date == expiry_0dte and c.type == 'call']
                call_strikes = sorted([c.strike_price for c in calls])
                atm_call_strike = min(call_strikes, key=lambda x: abs(x - spy_open)) if call_strikes else None
                higher_call_strike = min([s for s in call_strikes if s > atm_call_strike], default=None) if atm_call_strike else None
                if None in [atm_call_strike, higher_call_strike]:
                    skip_reason = 'No suitable strikes for call credit spread'
                short_call = next((c for c in calls if c.strike_price == atm_call_strike), None)
                long_call = next((c for c in calls if c.strike_price == higher_call_strike), None)
                if None in [short_call, long_call]:
                    skip_reason = 'No suitable contracts for call credit spread'
                legs_info = []
                for leg, side in zip([short_call, long_call], ['sell', 'buy']):
                    if leg is None:
                        break
                    symbol = occ_option_symbol('SPY', expiry_0dte, 'call', leg.strike_price)
                    open_px, close_px = get_option_open_close(option_client, symbol, day)
                    if open_px is None or close_px is None:
                        break
                    legs_info.append({'symbol': symbol, 'side': side, 'open': open_px, 'close': close_px})
                if len(legs_info) != 2:
                    skip_reason = 'Missing open/close prices for call credit spread legs'
                entry_premium = sum(l['open'] if l['side']=='sell' else -l['open'] for l in legs_info)
                exit_premium = sum(l['close'] if l['side']=='sell' else -l['close'] for l in legs_info)
                legs = legs_info
            elif strategy == 'IRON_BUTTERFLY':
                calls = [c for c in chain.values() if c.expiration_date == expiry_0dte and c.type == 'call']
                puts = [c for c in chain.values() if c.expiration_date == expiry_0dte and c.type == 'put']
                call_strikes = sorted([c.strike_price for c in calls])
                put_strikes = sorted([p.strike_price for p in puts])
                atm_call_strike = min(call_strikes, key=lambda x: abs(x - spy_open)) if call_strikes else None
                atm_put_strike = min(put_strikes, key=lambda x: abs(x - spy_open)) if put_strikes else None
                otm_call_strike = min([s for s in call_strikes if s > atm_call_strike], default=None) if atm_call_strike else None
                otm_put_strike = max([s for s in put_strikes if s < atm_put_strike], default=None) if atm_put_strike else None
                if None in [atm_call_strike, atm_put_strike, otm_call_strike, otm_put_strike]:
                    skip_reason = 'No suitable strikes for iron butterfly'
                short_call = next((c for c in calls if c.strike_price == atm_call_strike), None)
                short_put = next((p for p in puts if p.strike_price == atm_put_strike), None)
                long_call = next((c for c in calls if c.strike_price == otm_call_strike), None)
                long_put = next((p for p in puts if p.strike_price == otm_put_strike), None)
                if None in [short_call, short_put, long_call, long_put]:
                    skip_reason = 'No suitable contracts for iron butterfly'
                legs_info = []
                for leg, side, opt_type in zip([short_call, short_put, long_call, long_put], ['sell', 'sell', 'buy', 'buy'], ['call', 'put', 'call', 'put']):
                    if leg is None:
                        break
                    expiry = expiry_0dte
                    symbol = occ_option_symbol('SPY', expiry, opt_type, leg.strike_price)
                    open_px, close_px = get_option_open_close(option_client, symbol, day)
                    if open_px is None or close_px is None:
                        break
                    legs_info.append({'symbol': symbol, 'side': side, 'open': open_px, 'close': close_px})
                if len(legs_info) != 4:
                    skip_reason = 'Missing open/close prices for iron butterfly legs'
                entry_premium = sum(l['open'] if l['side']=='sell' else -l['open'] for l in legs_info)
                exit_premium = sum(l['close'] if l['side']=='sell' else -l['close'] for l in legs_info)
                legs = legs_info
            else:
                skip_reason = f'No logic for strategy {strategy} or missing expiry_7dte'
            if skip_reason:
                print(f"[SKIP] {skip_reason} on {day.date()} (trade {trade_num+1})")
                continue
            # Risk management: Kelly sizing (simplified, per spread)
            max_risk = cash * MAX_RISK_PER_TRADE
            if strategy in ['IRON_CONDOR', 'IRON_BUTTERFLY']:
                width = 5
                risk_per_contract = width * 100 - abs(entry_premium) * 100
            elif strategy in ['PUT_CREDIT_SPREAD', 'CALL_CREDIT_SPREAD']:
                width = 5
                risk_per_contract = width * 100 - abs(entry_premium) * 100
            elif strategy == 'DIAGONAL':
                risk_per_contract = abs(entry_premium) * 100
            else:
                risk_per_contract = 1000
            contracts_to_trade = max(1, int(max_risk // risk_per_contract))
            pnl = (exit_premium - entry_premium) * 100 * contracts_to_trade
            cash += pnl
            daily_pnl += pnl
            with open(LOG_FILE, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    day.date(), strategy, contracts_to_trade, entry_premium, exit_premium, pnl, regime, str(legs)
                ])
            trades_today += 1
            if daily_pnl < -MAX_DAILY_LOSS * cash:
                break
    print(f"Backtest complete. Final cash: {cash:.2f}")

if __name__ == '__main__':
    main() 