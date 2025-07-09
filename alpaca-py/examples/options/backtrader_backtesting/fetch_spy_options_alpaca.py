import os
from datetime import datetime, timedelta
import pandas as pd
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest
import time

# Load .env
load_dotenv()
api_key = os.getenv("ALPACA_API_KEY")
secret_key = os.getenv("ALPACA_API_SECRET") or os.getenv("ALPACA_SECRET_KEY")

if not api_key or not secret_key:
    raise RuntimeError("API keys not set in .env file.")

client = TradingClient(api_key, secret_key, paper=True)

# Date range: last 3 months
end_date = datetime.now().date()
start_date = end_date - timedelta(days=90)

all_options = []
unique_expirations = set()

print(f"Fetching SPY options contracts from {start_date} to {end_date}...")

for n in range((end_date - start_date).days + 1):
    day = start_date + timedelta(days=n)
    # Only fetch on weekdays
    if day.weekday() >= 5:
        continue
    try:
        req = GetOptionContractsRequest(symbol="SPY")
        contracts = client.get_option_contracts(req)
        contract_list = getattr(contracts, 'option_contracts', [])
        for c in contract_list:
            exp = getattr(c, 'expiration_date', None)
            if exp:
                unique_expirations.add(exp)
            all_options.append({
                'query_date': day,
                'symbol': getattr(c, 'symbol', None),
                'type': getattr(c, 'type', None),
                'strike': getattr(c, 'strike_price', None),
                'expiration': exp,
                'bid': getattr(c, 'bid', None),
                'ask': getattr(c, 'ask', None),
                'last_quote_time': getattr(c, 'last_quote_time', None)
            })
        print(f"{day}: {len(contract_list)} contracts, {len(unique_expirations)} unique expirations so far.")
        time.sleep(0.5)  # Avoid rate limits
    except Exception as e:
        print(f"Error fetching for {day}: {e}")
        time.sleep(2)

# Save to CSV
if all_options:
    df = pd.DataFrame(all_options)
    df.to_csv("spy_options_3mo.csv", index=False)
    print(f"Saved {len(df)} option records to spy_options_3mo.csv")
    print(f"Found {len(unique_expirations)} unique expirations.")
else:
    print("No options data fetched.") 