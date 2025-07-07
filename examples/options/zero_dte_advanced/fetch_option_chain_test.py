import os
from datetime import datetime
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest

# Robustly find and load .env from the project root

def find_project_root_with_env(start_path):
    current = os.path.abspath(start_path)
    while not os.path.exists(os.path.join(current, '.env')) and current != os.path.dirname(current):
        current = os.path.dirname(current)
    return current

project_root = find_project_root_with_env(__file__)
dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=dotenv_path)

api_key = os.getenv("ALPACA_API_KEY")
secret_key = os.getenv("ALPACA_SECRET_KEY")

client = TradingClient(api_key, secret_key, paper=True)

expiry = datetime.now().date()
print(f"Fetching SPY option contracts for expiry: {expiry}")

contracts_request = GetOptionContractsRequest(
    underlying_symbols=["SPY"],
    expiration_date=expiry,
    limit=1000
)
response = client.get_option_contracts(contracts_request)
option_contracts = getattr(response, 'option_contracts', None)
if option_contracts is None:
    option_contracts = []
print("Total contracts returned:", len(option_contracts))
print("Types found:", set(c.type for c in option_contracts))
print("First 10 contracts:")
for c in option_contracts[:10]:
    print(vars(c))
expiries = set(getattr(c, 'expiration_date', None) for c in option_contracts)
expiries_sorted = sorted(e for e in expiries if e is not None)
print("Unique expirations in contracts:", expiries_sorted)
calls = [c for c in option_contracts if c.type == 'call']
puts = [c for c in option_contracts if c.type == 'put']
print("Call strikes:", sorted(set(c.strike_price for c in calls)))
print("Put strikes:", sorted(set(p.strike_price for p in puts))) 