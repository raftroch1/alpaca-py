import os
from datetime import datetime
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

API_KEY = os.environ.get("ALPACA_API_KEY")
SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY")

if not API_KEY or not SECRET_KEY:
    print("[ERROR] Missing Alpaca API credentials.")
    exit(1)

client = StockHistoricalDataClient(api_key=API_KEY, secret_key=SECRET_KEY)
try:
    bars = client.get_stock_bars(
        StockBarsRequest(
            symbol_or_symbols=["SPY"],
            timeframe=TimeFrame.Day,
            start=datetime(2025, 4, 1),
            end=datetime(2025, 4, 2)
        )
    )
    if bars and "SPY" in bars and len(bars["SPY"]) > 0:
        print("[SUCCESS] SPY daily bar fetched:")
        for bar in bars["SPY"]:
            print(bar)
    else:
        print("[FAIL] No SPY bars returned. Check your subscription and API keys.")
except Exception as e:
    print(f"[ERROR] Exception while fetching SPY bars: {e}") 