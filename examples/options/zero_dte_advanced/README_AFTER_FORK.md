# Alpaca Options Strategies – Post-Fork README

## Overview
This project is a robust, research-driven extension of the original Alpaca options trading repo. After forking, we have:
- Refactored and modularized strategy code for multi-leg options (Iron Condor, Iron Butterfly, Credit Spreads, Diagonal)
- Centralized all logs and outputs in a dated `logs/` folder for each strategy
- Cleaned and organized the codebase for clarity and future development
- Begun planning for advanced risk management, profit-taking, and Telegram bot integration

## Project Structure
```
examples/
  options/
    zero_dte_advanced/
      adaptive_options_strategy.py   # Adaptive regime-based live strategy
      multi_regime_options_strategy.py # Multi-strategy, multi-leg live strategy
      logs/                         # All logs and CSVs, organized by date
    backtesting/                    # (Planned) Backtesting scripts for new strategies
    tests/                          # (Planned) Unit and integration tests

alpaca-py/
  Makefile
  Dockerfile
  .dockerignore
  .pre-commit-config.yaml
  pyproject.toml
  poetry.lock
  ...
```

## Key Changes After Forking
- **Strategy Refactor:** All multi-leg order logic now uses Alpaca's official multi-leg API (`OrderClass.MLEG`), ensuring trades are recognized as covered/risk-defined.
- **Logging:** All logs and CSVs are now written to a `logs/` subfolder inside each strategy directory, with filenames including the date and time for easy tracking.
- **Cleanup:** Removed legacy, test, and backtesting scripts that were not aligned with the new architecture. The codebase is now focused and ready for robust development.
- **Preparation for Risk Management:** The current strategies hold positions until expiry. Next, we will add stop loss, take profit, and dynamic risk controls.
- **Backtesting Integration:** The new backtesting engine will be adapted to match the live strategy logic, ensuring realistic performance analysis.
- **Telegram Bot Roadmap:** We will integrate a Telegram bot for trade alerts, subscription management, and user interaction, using a modular, async, and scalable template.

## Infrastructure & DevOps
- **Makefile:** Present for streamlined development workflows (linting, testing, etc.)
- **Dockerfile & .dockerignore:** Present for containerized deployment and reproducibility
- **Pre-commit hooks:** Configured for code quality
- **CI/CD:** (Planned) Integrate with GitHub Actions or similar for automated testing and deployment

## Roadmap / Next Steps
1. **Complete Strategy Logic:**
   - Implement robust risk management (stop loss, take profit, position sizing)
   - Add profit-taking and early exit logic
   - Finalize all regime/strategy selection logic
2. **Backtesting Engine:**
   - Adapt backtesting scripts to match live strategy logic
   - Ensure all logs/outputs are consistent and comparable
3. **Testing:**
   - Add unit and integration tests for all major modules
4. **Telegram Bot Integration:**
   - Build a modular Telegram bot for trade alerts, user management, and payments (see `tasks.md` for details)
5. **Penny Stock Strategy:**
   - Develop and integrate a penny stock filtering and trading module
6. **DevOps:**
   - Leverage Makefile, Docker, and pre-commit for robust, reproducible workflows

## Contributing
- Please see `tasks.md` for open tasks and progress tracking
- Follow the project structure and logging conventions
- PRs should be clear, well-documented, and tested

---
For questions or collaboration, open an issue or contact the maintainer.

## Cloning and Working with Submodules

This repo uses the `alpaca-py` directory as a git submodule. To ensure you have all code (including the SDK) when cloning or updating, follow these steps:

### Cloning the Repo (with Submodules)
```bash
git clone --recurse-submodules <your-repo-url>
```
- This will clone both your main repo and the `alpaca-py` submodule at the correct commit.

### If You Already Cloned Without Submodules
If you already cloned the repo and the `alpaca-py` folder is empty or missing, run:
```bash
git submodule update --init --recursive
```
- This will fetch and initialize the submodule(s).

### When Pulling New Changes
If you pull new changes that update the submodule pointer, also run:
```bash
git submodule update --recursive
```

### Summary Table
| Action                | Command                                                      |
|-----------------------|-------------------------------------------------------------|
| Clone with submodules | `git clone --recurse-submodules <repo-url>`                 |
| Init submodules later | `git submodule update --init --recursive`                   |
| Update submodules     | `git submodule update --recursive`                          |

**As long as you follow these steps, you will have no issues working with the repo and its submodule on any computer.**

If you ever want to remove the submodule and make it a regular folder, see the git documentation or ask the maintainer for guidance. 