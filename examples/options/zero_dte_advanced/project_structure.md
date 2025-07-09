# Project Structure

This document describes the current and planned structure of the Alpaca Options Strategies repo after the fork and cleanup.

## Directory Layout

```
repo-root/
│
├── alpaca-py/                # Alpaca official Python SDK (as submodule)
│   ├── Makefile              # Dev workflow automation
│   ├── Dockerfile            # Containerization
│   ├── .dockerignore         # Docker build exclusions
│   ├── .pre-commit-config.yaml # Pre-commit hooks
│   ├── pyproject.toml        # Python project config
│   ├── poetry.lock           # Dependency lockfile
│   ├── README.md             # SDK documentation
│   └── ...
│
├── examples/
│   └── options/
│       ├── zero_dte_advanced/
│       │   ├── adaptive_options_strategy.py   # Adaptive regime-based live strategy
│       │   ├── multi_regime_options_strategy.py # Multi-strategy, multi-leg live strategy
│       │   ├── logs/                         # All logs and CSVs, organized by date
│       │   ├── README_AFTER_FORK.md          # Post-fork project overview
│       │   ├── tasks.md                      # Project task tracker
│       │   └── project_structure.md          # This file
│       │
│       ├── backtesting/                      # (Planned) Backtesting scripts for new strategies
│       └── tests/                            # (Planned) Unit and integration tests
│
├── .gitignore
└── ...
```

## Folder & File Descriptions
- **alpaca-py/**: The official Alpaca Python SDK, included as a submodule. Contains all core trading, data, and API logic.
- **examples/options/zero_dte_advanced/**: Main directory for advanced, multi-leg options strategies and logs.
  - `adaptive_options_strategy.py`: Adaptive regime-based live trading strategy.
  - `multi_regime_options_strategy.py`: Multi-strategy, multi-leg live trading strategy.
  - `logs/`: All logs and CSVs, named by date and time for easy tracking.
  - `README_AFTER_FORK.md`: Overview of changes and project direction post-fork.
  - `tasks.md`: Task and progress tracker for the project.
  - `project_structure.md`: This file, describing the repo layout.
- **examples/options/backtesting/**: (Planned) Scripts for backtesting the new strategies.
- **examples/options/tests/**: (Planned) Unit and integration tests for strategies and infrastructure.
- **Makefile, Dockerfile, .dockerignore, .pre-commit-config.yaml**: Infrastructure for dev workflows, containerization, and code quality.

## Conventions
- All logs and outputs are stored in `logs/` folders, organized by date.
- New features and modules should be added in a modular, testable way.
- Keep this file updated as the project evolves. 