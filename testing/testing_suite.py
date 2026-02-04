import json
import time
import random
import requests
from datetime import datetime, timedelta
import pandas as pd

API_URL_SINGLE = "http://localhost:9013/forecast"
API_URL_BATCH = "http://localhost:9013/batch_forecast"
API_KEY = "mykey2023"
HEADERS = {"Content-Type": "application/json", "X-API-KEY": API_KEY}

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

# Define your scenario matrix
single_scenarios = []
for num_points in [1000, 5000, 20000,90000]:
    for tz in [False, True]:
        for gap in [True, False]:
            for mod in [0.1,0.5, 1.0, 2.0,250]:
                # forecast period always 1h ahead in these tests
                forecast_start = datetime.utcnow() + timedelta(minutes=1)
                forecast_end   = forecast_start + timedelta(hours=1)
                single_scenarios.append({
                    "data_points": num_points,
                    "tz_aware": tz,
                    "use_gap_detection": gap,
                    "model_size_modulator": mod,
                    "forecast_period": {
                        "start": forecast_start.isoformat(),
                        "end":   forecast_end.isoformat()
                    },
                    "interval_seconds": 60
                })

batch_scenarios = []
for series_count in [1, 3, 10]:
    for points_per_series in [1000, 20000]:
        for gap in [False, True]:
            for mod in [0.5, 1.0]:
                forecast_start = datetime.utcnow() + timedelta(minutes=1)
                forecast_end   = forecast_start + timedelta(hours=1)
                batch_scenarios.append({
                    "series_count": series_count,
                    "points_per_series": points_per_series,
                    "use_gap_detection": gap,
                    "model_size_modulator": mod,
                    "forecast_period": {
                        "start": forecast_start.isoformat(),
                        "end":   forecast_end.isoformat()
                    },
                    "interval_seconds": 60
                })

results = []

def run_single_test(idx, params):
    payload = {
        "data": generate_series(params["data_points"], params["tz_aware"]),
        "forecast_period": params["forecast_period"],
        "interval_seconds": params["interval_seconds"],
        "use_gap_detection": params["use_gap_detection"],
        "model_size_modulator": params["model_size_modulator"]
    }
    start = time.time()
    resp = requests.post(API_URL_SINGLE, headers=HEADERS, json=payload)
    elapsed = time.time() - start
    success = resp.status_code == 200
    return {
        "test_id": f"SINGLE_{idx}",
        "endpoint": "single",
        "total_time_s": round(elapsed, 2),
        "success": success,
        "error_code": None if success else resp.status_code,
        "parameters": {
            "data_points": params["data_points"],
            "tz_aware": params["tz_aware"],
            "use_gap": params["use_gap_detection"],
            "modulator": params["model_size_modulator"]
        }
    }

def run_batch_test(idx, params):
    series_list = []
    for i in range(params["series_count"]):
        series_list.append({
            "id": f"series_{i+1}",
            "data": generate_series(params["points_per_series"]),
            "forecast_period": params["forecast_period"],
            "interval_seconds": params["interval_seconds"],
            "use_gap_detection": params["use_gap_detection"],
            "model_size_modulator": params["model_size_modulator"]
        })
    payload = {"series": series_list}
    start = time.time()
    resp = requests.post(API_URL_BATCH, headers=HEADERS, json=payload)
    elapsed = time.time() - start
    success = resp.status_code == 200
    return {
        "test_id": f"BATCH_{idx}",
        "endpoint": "batch",
        "total_time_s": round(elapsed, 2),
        "success": success,
        "error_code": None if success else resp.status_code,
        "parameters": {
            "series_count": params["series_count"],
            "points_per_series": params["points_per_series"],
            "use_gap": params["use_gap_detection"],
            "modulator": params["model_size_modulator"]
        }
    }

# Run all single tests
for i, scen in enumerate(single_scenarios, 1):
    results.append(run_single_test(i, scen))

# Run all batch tests
for i, scen in enumerate(batch_scenarios, 1):
    results.append(run_batch_test(i, scen))

# Summarize with pandas
df = pd.DataFrame(results)
print(df.to_string(index=False))

# Optionally save to CSV:
df.to_csv("forecast_test_results.csv", index=False)
print("\nResults also written to forecast_test_results.csv")
