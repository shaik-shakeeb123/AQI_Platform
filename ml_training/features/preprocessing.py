import pandas as pd
import numpy as np
from typing import List, Dict, Any, Union

# Centralized constant for missing value imputation defaults
DEFAULT_IMPUTATIONS = {
    "pm25": 25.0,
    "pm10": 50.0,
    "no2": 20.0,
    "o3": 30.0,
    "co": 500.0,  # 0.5 mg/m3 * 1000 = 500 ug/m3
    "so2": 10.0,
    "temperature": 25.0,
    "humidity": 60.0,
    "wind_speed": 2.0,
    "wind_direction": 180.0,
    "precipitation": 0.0,
    "pressure": 1013.0
}

def clean_and_format_timestamps(df: pd.DataFrame, timestamp_col: str = "timestamp") -> pd.DataFrame:
    """Ensure timestamp is datetime and sorted chronologically."""
    df = df.copy()
    df[timestamp_col] = pd.to_datetime(df[timestamp_col])
    df = df.sort_values(timestamp_col)
    df = df[~df[timestamp_col].duplicated(keep="first")].reset_index(drop=True)
    return df

def resample_time_series(df: pd.DataFrame, timestamp_col: str = "timestamp", frequency: str = "1h") -> pd.DataFrame:
    """Resample dataframe to a strict 1-hour grid."""
    df = df.copy()
    df = df.set_index(timestamp_col)
    df = df.resample(frequency).asfreq()
    
    # Fill static columns completely
    static_cols = ["city", "location_name", "latitude", "longitude"]
    for col in static_cols:
        if col in df.columns:
            df[col] = df[col].ffill().bfill()
            
    df = df.reset_index()
    return df

def interpolate_gaps(df: pd.DataFrame, limit: int = 3) -> pd.DataFrame:
    """Linearly interpolate numerical columns with forward and backward fill constraints."""
    df = df.copy()
    static_cols = ["city", "location_name", "latitude", "longitude", "timestamp"]
    numeric_cols = [c for c in df.columns if c not in static_cols and np.issubdtype(df[c].dtype, np.number)]
    
    # Linearly interpolate numeric values
    df[numeric_cols] = df[numeric_cols].interpolate(method="linear", limit=limit)
    
    # Impute missing values with forward-fill then backward-fill (limit=3 hours)
    df[numeric_cols] = df[numeric_cols].ffill(limit=limit).bfill(limit=limit)
    
    return df

def convert_co_units(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure CO is converted from mg/m3 to ug/m3 (1000x conversion)."""
    df = df.copy()
    if "co" in df.columns:
        # Check if values are mg/m3 and need scaling. 
        # Live OpenAQ typically yields mg/m3 (e.g. 0.5), we scale to ug/m3 (e.g. 500).
        df["co"] = df["co"] * 1000.0
    return df

def impute_missing_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Fill missing columns and any remaining NaNs with default values."""
    df = df.copy()
    for col, val in DEFAULT_IMPUTATIONS.items():
        if col in df.columns:
            df[col] = df[col].fillna(val)
        else:
            df[col] = val
    return df

def run_preprocessing_pipeline(history: Union[List[Dict[str, Any]], pd.DataFrame]) -> pd.DataFrame:
    """Stateless entrypoint to clean, resample, interpolate, scale and impute a dataset."""
    if isinstance(history, list):
        df = pd.DataFrame(history)
    else:
        df = history.copy()
        
    if df.empty:
        return pd.DataFrame()
        
    # Standardize column mappings if needed
    if "recorded_at" in df.columns and "timestamp" not in df.columns:
        df["timestamp"] = df["recorded_at"]
        
    df = (
        df.pipe(clean_and_format_timestamps)
          .pipe(resample_time_series)
          .pipe(interpolate_gaps)
          .pipe(convert_co_units)
          .pipe(impute_missing_columns)
    )
    return df

def resample_and_interpolate_segments(
    group: pd.DataFrame,
    gap_threshold_hours: float = 12.0,
    interpolation_limit_hours: int = 3
) -> pd.DataFrame:
    """Splits historical station group into segments and processes each using the standard grid/interpolation logic."""
    if len(group) < 2:
        return pd.DataFrame()
        
    group = group.copy()
    if "timestamp" not in group.columns and "recorded_at" in group.columns:
        group["timestamp"] = pd.to_datetime(group["recorded_at"])
        
    # Deduplicate and sort
    group = group.sort_values("timestamp")
    group = group[~group["timestamp"].duplicated(keep="first")].reset_index(drop=True)
    
    if len(group) < 2:
        return pd.DataFrame()
        
    time_diffs = group["timestamp"].diff()
    max_gap = pd.Timedelta(hours=gap_threshold_hours)
    segment_ids = (time_diffs > max_gap).cumsum()
    
    resampled_segments = []
    
    for seg_id, seg_group in group.groupby(segment_ids):
        if len(seg_group) < 2:
            continue
            
        # Run preprocessing pipeline on the segment
        processed = run_preprocessing_pipeline(seg_group)
        if not processed.empty:
            resampled_segments.append(processed)
            
    if not resampled_segments:
        return pd.DataFrame()
        
    return pd.concat(resampled_segments, ignore_index=True)
