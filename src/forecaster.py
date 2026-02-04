import pandas as pd
import numpy as np
from dateutil import tz
from xgboost import XGBRegressor

# 1) NumPy-level (affects underlying repr of arrays):
np.set_printoptions(suppress=True)

# 2) pandas-level (affects DataFrame pretty-printing):
pd.options.display.float_format = '{:.6f}'.format

def forecast_xgb_timeseries(
    data,
    forecast_period,
    interval_seconds,
    use_gap_detection=False,
    training_period=None,
    predictor_options=None,
    model_size_modulator=3.0,
):
    """
    Forecast a time series using XGBoost with optional gap trimming and custom training period.

    Automatically handles any datetime string or datetime object (with or without tz),
    uses UTC internally, and returns forecasts in the same tz as input.
    """
    # Load into DataFrame and parse timestamps
    df = pd.DataFrame(data)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=False)

    # Detect input timezone using first timestamp (default UTC if none)
    first_ts = df['timestamp'].iloc[0]
    input_tz = first_ts.tzinfo or tz.UTC

    # Helper to localize or convert to UTC
    def to_utc(ts_series):
        if ts_series.dt.tz is None:
            return (
                ts_series
                .dt.tz_localize(input_tz, ambiguous=True, nonexistent='shift_forward')
                .dt.tz_convert(tz.UTC)
            )
        else:
            return ts_series.dt.tz_convert(tz.UTC)

    # Convert all timestamps to UTC
    df['timestamp'] = to_utc(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)

    # Apply training-period slicing or gap detection
    if training_period is not None:
        t0 = pd.to_datetime(training_period[0], utc=False)
        t1 = pd.to_datetime(training_period[1], utc=False)
        t0_utc = to_utc(pd.Series(t0)).iloc[0]
        t1_utc = to_utc(pd.Series(t1)).iloc[0]
        df = df[(df['timestamp'] >= t0_utc) & (df['timestamp'] <= t1_utc)].reset_index(drop=True)
    elif use_gap_detection:
        diffs = df['timestamp'].diff().dropna()
        threshold = diffs.median() * 3
        gaps = diffs > threshold
        if gaps.any():
            last_gap = gaps[gaps].index.max()
            df = df.loc[last_gap+1:].reset_index(drop=True)

    # Resample & interpolate to uniform interval
    freq_str = f"{int(interval_seconds)}S"
    df = df.set_index('timestamp').resample(freq_str).mean()
    df['value'] = df['value'].interpolate()

    # Feature engineering: time index + Fourier terms
    df_feat = df.copy()
    df_feat['t'] = df_feat.index.view(np.int64) / 1e9
    span = df_feat.index.max() - df_feat.index.min()

    def add_fourier(dframe, period, order):
        for k in range(1, order + 1):
            dframe[f"sin_{period}_{k}"] = np.sin(2 * np.pi * k * dframe['t'] / period)
            dframe[f"cos_{period}_{k}"] = np.cos(2 * np.pi * k * dframe['t'] / period)

    sec_day = 86400
    add_fourier(df_feat, sec_day, 2)
    sec_week = sec_day * 7
    if span >= pd.Timedelta(days=7):
        add_fourier(df_feat, sec_week, 2)
    sec_year = sec_day * 365.25
    if span >= pd.Timedelta(days=365):
        add_fourier(df_feat, sec_year, 3)

    # Train XGB model
    trees = max(1, int(model_size_modulator * 100))
    opts = {
        'objective': 'reg:squarederror',
        'n_estimators': trees,
        'max_depth': int(6 + model_size_modulator**0.25),
        'learning_rate': 50 / trees,
        'subsample': 1.0,
        'colsample_bytree': 1.0
    }
    if isinstance(predictor_options, dict):
        opts.update(predictor_options)
    model = XGBRegressor(**opts)
    model.fit(df_feat.drop(columns=['value']), df_feat['value'])

    # Build future UTC index for forecasting
    start, end = forecast_period
    start_ts = pd.to_datetime(start, utc=False)
    end_ts = pd.to_datetime(end, utc=False)
    start_utc = to_utc(pd.Series(start_ts)).iloc[0]
    end_utc = to_utc(pd.Series(end_ts)).iloc[0]
    idx_utc = pd.date_range(start=start_utc, end=end_utc, freq=freq_str, tz=tz.UTC)

    # Prepare features for forecast
    df_pred = pd.DataFrame(index=idx_utc)
    df_pred['t'] = df_pred.index.view(np.int64) / 1e9
    add_fourier(df_pred, sec_day, 2)
    if span >= pd.Timedelta(days=7):
        add_fourier(df_pred, sec_week, 2)
    if span >= pd.Timedelta(days=365):
        add_fourier(df_pred, sec_year, 3)

    df_pred['forecast'] = model.predict(df_pred)

    # Convert forecasts back to original timezone and format
    df_pred = df_pred.tz_convert(input_tz)
    out = pd.DataFrame({
        'forecast': df_pred['forecast'].values
    }, index=[ts.isoformat() for ts in df_pred.index])

    # Filter small values: set any forecast < 1e-5 to zero
    out['forecast'] = out['forecast'].mask(out['forecast'] < 1e-5, 0.0)

    return out
