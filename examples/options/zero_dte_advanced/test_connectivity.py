import os
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.common.exceptions import APIError
from alpaca.trading.models import TradeAccount

# Robustly find and load .env from the project root (where .env.example is)
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
base_url = os.getenv("ALPACA_API_BASE_URL", "https://paper-api.alpaca.markets")

if not api_key or not secret_key:
    raise RuntimeError("API keys not set in .env file.")

try:
    client = TradingClient(api_key, secret_key, paper=True, url_override=base_url)
    account = client.get_account()
    if isinstance(account, TradeAccount):
        print("Connection successful!")
        print(f"Account ID: {account.id}")
        print(f"Account status: {account.status}")
    else:
        print("Connection successful, but unexpected account object type:")
        print(account)
except APIError as e:
    print("API Error:", e)
except Exception as e:
    print("Connection failed:", e) 