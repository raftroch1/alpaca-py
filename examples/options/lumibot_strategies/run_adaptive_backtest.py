from lumibot.backtesting import Backtest
from lumibot.data.sources import AlpacaData
from adaptive_options_lumibot import AdaptiveOptionsLumibot
import os

# Set your Alpaca API keys (use environment variables or .env for security)
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")

# Configure the data source for backtesting (AlpacaData)
data_source = AlpacaData(
    api_key=ALPACA_API_KEY,
    api_secret=ALPACA_SECRET_KEY,
    paper=True,
    use_polygon=False  # Set to True if you have Polygon access
)

# Set up the backtest
backtest = Backtest(
    strategy_class=AdaptiveOptionsLumibot,
    data_source=data_source,
    start_date="2023-01-01",
    end_date="2023-06-30",
    initial_cash=10000,
    benchmark_asset="SPY"
)

# Run the backtest
if __name__ == "__main__":
    results = backtest.run()
    print(results) 