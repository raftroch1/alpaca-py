import os
from datetime import datetime

# Ensure logs directory exists
logs_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(logs_dir, exist_ok=True)

# Helper for timestamped log/csv filenames
now_str = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
log_path = os.path.join(logs_dir, f"multi_regime_{now_str}.log")
csv_path = os.path.join(logs_dir, f"multi_regime_{now_str}.csv")

# Wherever you write logs or CSVs, use log_path/csv_path instead of a root-level file
# For example, to write a log:
# with open(log_path, 'a') as f:
#     f.write('...')
# To write a CSV:
# with open(csv_path, 'w', newline='') as f:
#     writer = csv.writer(f)
#     writer.writerow([...]) 