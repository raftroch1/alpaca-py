# Advanced 0DTE SPY Options Strategy

This directory contains an advanced, multi-factor 0DTE (zero days to expiration) SPY options trading strategy implemented in Python using the Alpaca API.

## Features
- Anchored VWAPs at key pivot points
- Volume Profile (POC, Value Areas)
- ATR-based volatility and position sizing
- EMA crossovers (multi-timeframe)
- Market regime detection (volatility/trend)
- Momentum confluence (MACD, RSI, volume)
- Options chain analysis (gamma risk, liquidity)
- Dynamic position sizing (ATR, Kelly Criterion)
- Smart risk management (dynamic stops, daily loss limits)
- Multiple exit strategies (profit, stop, time-based)

## Setup Instructions

### 1. **Conda Environment Setup**
This project is designed to run in the `Alpaca_Options` Conda environment.

- **Create the environment (if not already created):**
  ```bash
  conda create -n Alpaca_Options python=3.10
  conda activate Alpaca_Options
  ```
- **Or, to reproduce the exact environment:**
  ```bash
  conda env create -f environment.yml
  conda activate Alpaca_Options
  ```

- **Agent Mode:**
  > Always ensure you are running in the `Alpaca_Options` environment when using agent mode or executing scripts.

### 2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
### 3. **Set your Alpaca API keys using a .env file:**
   - Copy `.env.example` to `.env` and fill in your credentials:
     ```bash
     cp .env.example .env
     # Edit .env and add your keys
     ```
   - The script will automatically load these variables.
### 4. **Run the strategy:**
   - Edit `strategy.py` to adjust parameters if needed.
   - Uncomment the last line in `strategy.py` to enable live trading:
     ```python
     # asyncio.run(strategy.run_strategy())
     ```
   - Then run:
     ```bash
     python strategy.py
     ```

**Note:**
- This strategy is for educational purposes. Start with paper trading.
- Requires an Alpaca paper trading account.
- For best results, run during US market hours.

## File Structure
- `strategy.py` — Main strategy implementation
- `requirements.txt` — Python dependencies
- `environment.yml` — Conda environment specification
- `.env.example` — Example environment variable file
- `README.md` — This documentation

## Enhancements & Ideas
- Add real-time options data and Greeks
- Implement backtesting module
- Integrate economic calendar filter
- Add position correlation limits

---

For questions or improvements, open an issue or PR. 