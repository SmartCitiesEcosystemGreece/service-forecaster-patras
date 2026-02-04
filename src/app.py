import os
from flask import Flask, request, jsonify, abort
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
from datetime import datetime
from forecaster import forecast_xgb_timeseries
from functools import wraps
# Load environment variables
load_dotenv()
API_KEY_FILE = os.environ["API_KEY_FILE"]
MAX_TRAIN_POINTS = int(os.environ["MAX_TRAIN_POINTS"])
MAX_FORECAST_POINTS = int(os.environ["MAX_FORECAST_POINTS"])
MAX_SERIES_PER_BATCH = int(os.environ["MAX_SERIES_PER_BATCH"])
MIN_INTERVAL_SECONDS = int(os.environ["MIN_INTERVAL_SECONDS"])
MAX_INTERVAL_SECONDS = int(os.environ["MAX_INTERVAL_SECONDS"])
FIDELITY_MIN = float(os.environ["FIDELITY_MIN"])
FIDELITY_MAX = float(os.environ["FIDELITY_MAX"])
RATE_LIMIT = os.environ["RATE_LIMIT_PER_MINUTE"]
from flask_cors import CORS
# Load API keys
with open(API_KEY_FILE) as f:
    VALID_KEYS = {line.strip() for line in f if line.strip()}

app = Flask(__name__)
limiter = Limiter(
    app,
    key_func=lambda: request.headers.get('X-API-KEY', get_remote_address()),
    default_limits=[RATE_LIMIT]
)

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get('X-API-KEY')
        if not key or key not in VALID_KEYS:
            abort(401, 'Invalid or missing API key')
        return f(*args, **kwargs)
    return decorated

# Parameter validation
from datetime import timedelta

def validate_params(params):
    # training points limit
    if len(params.get('data', [])) > MAX_TRAIN_POINTS:
        abort(400, f"Training data too long: max {MAX_TRAIN_POINTS} points allowed.")
    # interval
    interval = params.get('interval_seconds')
    if not (MIN_INTERVAL_SECONDS <= interval <= MAX_INTERVAL_SECONDS):
        abort(400, f"interval_seconds must be between {MIN_INTERVAL_SECONDS} and {MAX_INTERVAL_SECONDS}")
    # forecast points limit
    start = datetime.fromisoformat(params['forecast_period']['start'])
    end = datetime.fromisoformat(params['forecast_period']['end'])
    points = (end - start).total_seconds() / interval
    if points > MAX_FORECAST_POINTS:
        abort(400, f"Forecast period too long: max {MAX_FORECAST_POINTS} points allowed.")
    # fidelity
    fidelity = params.get('model_size_modulator', 1.0)
    if not (FIDELITY_MIN <= fidelity <= FIDELITY_MAX):
        abort(400, f"model_size_modulator must be between {FIDELITY_MIN} and {FIDELITY_MAX}")

ALLOWED_INTERVALS = [
    1, 2, 3, 4, 5, 10, 15, 30, 60,
    120, 300, 600, 900, 1200, 1800, 3600,
    7200, 10800, 14400, 18000, 21600,
    28800, 43200, 86400, 172800
]

@app.route('/ngsi-ld/batch_forecast', methods=['POST'])
@require_api_key
@limiter.limit(RATE_LIMIT)
def ngsi_ld_batch_forecast():
    payload = request.get_json(force=True)
    if not isinstance(payload, list):
        abort(400, "Payload must be a JSON array of entities.")

    # parse and validate user window
    timerel      = request.args.get('timerel')
    time_str     = request.args.get('time')
    end_time_str = request.args.get('endTime')
    if timerel != 'between' or not time_str or not end_time_str:
        abort(400, "Must supply timerel=between, time and endTime in ISO format")
    try:
        period_start = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
        period_end   = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
    except (TypeError, ValueError):
        abort(400, f"Invalid ISO timestamp for time or endTime: {time_str}, {end_time_str}")
    if period_end <= period_start:
        abort(400, "endTime must be after time")

    # series count validation
    total_series = sum(
        len([k for k in ent if k not in ('id','type','dateObserved','@context')])
        for ent in payload
    )
    if total_series > MAX_SERIES_PER_BATCH:
        abort(400, f"Too many series: max {MAX_SERIES_PER_BATCH} allowed (got {total_series}).")

    interval_override = request.args.get('interval_seconds', type=int)
    output = []

    for entity in payload:
        # Prepare new entity structure without dateObserved
        new_ent = {
            'id': entity.get('id'),
            'type': entity.get('type'),
            '@context': entity.get('@context', [])
        }
        first_fc_timestamps = None

        for prop_uri in (k for k in entity if k not in ('id','type','dateObserved','@context')):
            raw = entity[prop_uri]
            data, metadata_list = [], []
            non_numeric = False

            # flatten & validate
            for batch in raw.get('values', []):
                for pt in batch.get('values', []):
                    try:
                        num = float(pt.get('value'))
                    except (TypeError, ValueError):
                        non_numeric = True
                        break
                    try:
                        ts = datetime.fromisoformat(pt.get('observedAt').replace('Z','+00:00'))
                    except (TypeError, ValueError):
                        abort(400, f"Invalid timestamp for {prop_uri}: {pt.get('observedAt')}")
                    data.append({'timestamp': ts.isoformat(), 'value': num})
                    metadata_list.append(pt.get('metadata', {}))
                if non_numeric:
                    break

            # fallback for non-numeric
            if non_numeric:
                if data:
                    last, last_meta = data[-1], metadata_list[-1]
                    fc_values = [{
                        'type': 'Property',
                        'values': [{
                            'metadata': last_meta,
                            'value': last['value'],
                            'observedAt': last['timestamp']
                        }]
                    } for _ in data]
                    new_ent[prop_uri] = {'type': 'Property', 'values': fc_values}
                else:
                    new_ent[prop_uri] = raw
                continue

            # data-length checks
            n = len(data)
            if n < 2:
                abort(400, f"Need at least two readings for {entity.get('id')}")
            if n > MAX_TRAIN_POINTS:
                abort(400, f"Training data too long: max {MAX_TRAIN_POINTS} points allowed.")

            # determine interval
            if interval_override:
                interval = interval_override
            else:
                times = [datetime.fromisoformat(d['timestamp']) for d in data]
                diffs = [(times[i] - times[i-1]).total_seconds() for i in range(1, len(times))]
                diffs_sorted = sorted(diffs)
                trim = int(len(diffs_sorted) * 0.15)
                trimmed = diffs_sorted[trim:-trim] if len(diffs_sorted) > 2*trim else diffs_sorted
                avg = sum(trimmed) / len(trimmed)
                interval = min(ALLOWED_INTERVALS, key=lambda x: abs(x - avg))

            if not (MIN_INTERVAL_SECONDS <= interval <= MAX_INTERVAL_SECONDS):
                abort(400, f"interval_seconds must be between {MIN_INTERVAL_SECONDS} and {MAX_INTERVAL_SECONDS}")
            if n > MAX_FORECAST_POINTS:
                abort(400, f"Forecast period too long: max {MAX_FORECAST_POINTS} points allowed.")

            # use user window
            start, end = period_start, period_end

            # generate forecast
            df_fc = forecast_xgb_timeseries(
                data=data,
                forecast_period=[start.isoformat(), end.isoformat()],
                interval_seconds=interval,
                use_gap_detection=False
            )

            # ensure metadata_list covers all forecasted rows
            m = len(df_fc)
            if len(metadata_list) >= m:
                fc_metadata = metadata_list[:m]
            else:
                last_meta = metadata_list[-1]
                fc_metadata = metadata_list + [last_meta] * (m - len(metadata_list))

            # rebuild nested values
            fc_values = []
            for idx, (ts, row) in enumerate(df_fc.iterrows()):
                ts_str = ts if isinstance(ts, str) else ts.isoformat()
                fc_values.append({
                    'type': 'Property',
                    'values': [{
                        'metadata': fc_metadata[idx],
                        'value': float(row['forecast']),
                        'observedAt': ts_str
                    }]
                })

            # capture timestamps from the first forecasted series
            if first_fc_timestamps is None:
                first_fc_timestamps = [item['values'][0]['observedAt'] for item in fc_values]

            new_ent[prop_uri] = {'type': 'Property', 'values': fc_values}

        # after processing all properties, set dateObserved to forecasted timestamps
        if first_fc_timestamps:
            new_ent['dateObserved'] = {
                'type': 'Property',
                'values': first_fc_timestamps
            }

        output.append(new_ent)

    return jsonify(output)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 9013)))
