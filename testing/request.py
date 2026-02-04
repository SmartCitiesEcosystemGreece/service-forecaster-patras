import json
import time
from datetime import datetime, timedelta
import random
import requests

# Configuration
API_URL_SINGLE = "http://localhost:9013/forecast"
API_URL_BATCH = "http://localhost:9013/batch_forecast"
API_KEY = "mykey2023"

# Generate synthetic dataset: 20000 points, one per minute
def generate_series(num_points, tz_aware=False):
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(minutes=num_points - 1)
    data = []
    current = start_time
    for _ in range(num_points):
        value = 10 + random.uniform(-1, 1)
        ts = current.isoformat() + ("Z" if tz_aware else "")
        data.append({"timestamp": ts, "value": value})
        current += timedelta(minutes=1)
    return data

# Build single request payload
data_single = generate_series(20000)
forecast_start = datetime.utcnow() + timedelta(minutes=1)
forecast_end = forecast_start + timedelta(hours=1)
payload_single = {
    "data": data_single,
    "forecast_period": {"start": forecast_start.isoformat(), "end": forecast_end.isoformat()},
    "interval_seconds": 60,
    "use_gap_detection": True,
    "model_size_modulator": 1.0
}

headers = {"Content-Type": "application/json", "X-API-KEY": API_KEY}

# Test single endpoint
print("--- SINGLE FORECAST ---")
start = time.time()
resp = requests.post(API_URL_SINGLE, headers=headers, json=payload_single)
print(f"Status: {resp.status_code}, Time: {time.time() - start:.2f}s")
try:
    print(json.dumps(resp.json(), indent=2)[:500] + '...')
except Exception:
    print(resp.text)

# Build batch request payload
series_list = []
for i in range(10):  # test 3 series in batch
    series_list.append({
        "id": f"series_{i+1}",
        "data": generate_series(43200),
        "forecast_period": {"start": forecast_start.isoformat(), "end": forecast_end.isoformat()},
        "interval_seconds": 60,
        "use_gap_detection": False,
        "model_size_modulator": 1.0
    })
payload_batch = {"series": series_list}

# Test batch endpoint
print("\n--- BATCH FORECAST ---")
start = time.time()
resp = requests.post(API_URL_BATCH, headers=headers, json=payload_batch)
print(f"Status: {resp.status_code}, Time: {time.time() - start:.2f}s")
try:
    print(json.dumps(resp.json(), indent=2)[:500] + '...')
except Exception:
    print(resp.text)
