import os
import pandas as pd
from dotenv import load_dotenv
from alpaca.data.historical import OptionHistoricalDataClient
from alpaca.data.requests import OptionLatestQuoteRequest

# Load .env
load_dotenv()
api_key = os.getenv("ALPACA_API_KEY")
secret_key = os.getenv("ALPACA_API_SECRET") or os.getenv("ALPACA_SECRET_KEY")

# Load options data
options_df = pd.read_csv("spy_options_3mo.csv")

# Pick a single test day (first available date)
test_date = options_df["query_date"].iloc[0]
day_df = options_df[options_df["query_date"] == test_date]
symbols = day_df["symbol"].dropna().unique().tolist()

print(f"Fetching quotes for {len(symbols)} option contracts on {test_date}...")

# Fetch quotes
client = OptionHistoricalDataClient(api_key, secret_key)
request = OptionLatestQuoteRequest(symbol_or_symbols=symbols)
quotes = client.get_option_latest_quote(request)

# Print bid/ask for each symbol
for sym in symbols:
    q = quotes.get(sym)
    if q is not None:
        print(f"{sym}: bid={q.bid_price}, ask={q.ask_price}")
    else:
        print(f"{sym}: No quote data returned.")

# TODO: Batch requests for large symbol lists, loop over multiple days, merge into DataFrame, etc. 