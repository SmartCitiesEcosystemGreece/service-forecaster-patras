# NGSI-LD Batch Forecast API

This repository contains a small Flask service that accepts NGSI-LD style entities with time series values and returns a forecasted series for each numeric property. Forecasting is done with an XGBoost regressor using basic time features (including Fourier terms).

The main entrypoint is `src/app.py`. The forecasting logic is in `src/forecaster.py`.

## What it does

- Exposes a single HTTP endpoint: `POST /ngsi-ld/batch_forecast`
- Requires an API key provided in the `X-API-KEY` request header
- Applies request validation and rate limiting
- For each entity in the request:
  - For each property (excluding `id`, `type`, `dateObserved`, `@context`):
    - If values are numeric, it forecasts over the requested time window
    - If values are non-numeric, it falls back to repeating the last numeric value (or returns the raw data if no numeric points exist)
  - Returns a new entity with forecasted `values` and a `dateObserved` array containing forecast timestamps

## Repository layout

- `src/app.py` - Flask API for NGSI-LD batch forecasting
- `src/forecaster.py` - XGBoost-based time series forecaster
- `docker/Dockerfile` - container image definition
- `postman/ngsi_ld_batch_forecast.postman_collection.json` - Postman collection
- `api_keys.txt` - API key file (one key per line)
- `testing/` - ad-hoc test scripts (note: some scripts reference endpoints not present in `src/app.py`)

## Requirements

- Python 3.11 recommended (Dockerfile uses `python:3.11-slim`)
- Dependencies are listed in `requirements.txt`

Install locally:

```bash
pip install -r requirements.txt
```

## Configuration

`src/app.py` reads required settings from environment variables (typically via a `.env` file). If any required variable is missing, the app will fail at startup.

Required variables:

- `API_KEY_FILE` - path to a text file containing valid API keys (one per line)
- `MAX_TRAIN_POINTS` - maximum number of training points accepted per series
- `MAX_FORECAST_POINTS` - maximum number of forecast points allowed for the requested window
- `MAX_SERIES_PER_BATCH` - maximum number of property series across all entities in one request
- `MIN_INTERVAL_SECONDS` - minimum allowed interval
- `MAX_INTERVAL_SECONDS` - maximum allowed interval
- `FIDELITY_MIN` - minimum allowed `model_size_modulator`
- `FIDELITY_MAX` - maximum allowed `model_size_modulator`
- `RATE_LIMIT_PER_MINUTE` - rate limit string consumed by Flask-Limiter (example: `60 per minute`)

Optional:

- `PORT` - server port (defaults to 9013)

Example `.env`:

```dotenv
API_KEY_FILE=api_keys.txt
MAX_TRAIN_POINTS=20000
MAX_FORECAST_POINTS=10000
MAX_SERIES_PER_BATCH=100
MIN_INTERVAL_SECONDS=1
MAX_INTERVAL_SECONDS=172800
FIDELITY_MIN=0.1
FIDELITY_MAX=5.0
RATE_LIMIT_PER_MINUTE=60 per minute
PORT=9013
```

### API keys

Put one key per line in the file pointed to by `API_KEY_FILE` (for example, `api_keys.txt`):

```text
another-key
```

Requests must include:

- Header: `X-API-KEY: <key>`

## Run locally

From the repository root:

```bash
export $(cat .env | xargs)  # or use your own environment setup
python src/app.py
```

The service listens on `http://0.0.0.0:9013` by default.

## Run with Docker

The provided Dockerfile is `docker/Dockerfile`. 

Build and run (example):

```bash
docker build -f docker/Dockerfile -t ngsi-ld-forecast .
docker run --rm -p 9013:9013 --env-file .env ngsi-ld-forecast
```

## API

### POST /ngsi-ld/batch_forecast

- Auth: `X-API-KEY` header
- Rate limited (see `RATE_LIMIT_PER_MINUTE`)
- Body: JSON array of NGSI-LD entities

Required query parameters:

- `timerel=between`
- `time=<ISO timestamp>`
- `endTime=<ISO timestamp>`

Optional query parameters:

- `interval_seconds=<int>` - override interval detection

#### Request format (high level)

Each entity is expected to contain:

- `id`
- `type`
- `@context` (optional)
- One or more properties whose values are nested in the shape shown below

Each forecasted property is expected to look like:

```json
{
  "type": "Property",
  "values": [
    {
      "type": "Property",
      "values": [
        {
          "value": 12.34,
          "observedAt": "2026-01-01T00:00:00Z",
          "metadata": {}
        }
      ]
    }
  ]
}
```

The service flattens the nested structure under `values[*].values[*]` into a list of `(timestamp, value)` pairs, trains a model, then produces forecast points for the requested time window.

#### Example curl

```bash
curl -X POST "http://localhost:9013/ngsi-ld/batch_forecast?timerel=between&time=2026-01-01T00:00:00Z&endTime=2026-01-01T01:00:00Z"   -H "Content-Type: application/json"   -H "X-API-KEY: a-key"   -d @payload.json
```

#### Response

The response is a JSON array of entities with:

- the same `id`, `type`, `@context`
- forecasted properties in the same nested `values` structure
- `dateObserved` populated with the forecast timestamps (taken from the first forecasted series)

## Postman

A Postman collection is provided at:

- `postman/ngsi_ld_batch_forecast.postman_collection.json`

It defines variables:

- `NGSI_URL` (default: `http://localhost:9013`)
- `NGSI_API_KEY` (default: `a-key`)
