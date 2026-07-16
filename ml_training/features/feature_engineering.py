import pandas as pd

def add_temporal_features(df: pd.DataFrame) -> pd.DataFrame:
    """Extract hour and day of week from timestamp index."""
    df = df.copy()
    if "timestamp" in df.columns:
        df["hour"] = df["timestamp"].dt.hour
        df["day_of_week"] = df["timestamp"].dt.dayofweek
    return df

def add_lag_features(df: pd.DataFrame) -> pd.DataFrame:
    """Shift columns to construct lag features."""
    df = df.copy()
    if "pm25" in df.columns:
        df["pm25_lag_1"] = df["pm25"].shift(1)
        df["pm25_lag_3"] = df["pm25"].shift(3)
    if "pm10" in df.columns:
        df["pm10_lag_1"] = df["pm10"].shift(1)
    return df

def add_rolling_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute rolling window averages."""
    df = df.copy()
    if "pm25" in df.columns:
        df["pm25_roll_mean_3"] = df["pm25"].rolling(window=3, min_periods=1).mean()
        df["pm25_roll_mean_6"] = df["pm25"].rolling(window=6, min_periods=1).mean()
    if "pm10" in df.columns:
        df["pm10_roll_mean_3"] = df["pm10"].rolling(window=3, min_periods=1).mean()
    return df

def impute_lag_nans(df: pd.DataFrame) -> pd.DataFrame:
    """Robust fallback: fill lag-induced NaNs with the current values."""
    df = df.copy()
    for col in ["pm25_lag_1", "pm25_lag_3"]:
        if col in df.columns and "pm25" in df.columns:
            df[col] = df[col].fillna(df["pm25"])
    if "pm10_lag_1" in df.columns and "pm10" in df.columns:
        df["pm10_lag_1"] = df["pm10_lag_1"].fillna(df["pm10"])
    return df

def run_feature_pipeline(df: pd.DataFrame) -> pd.DataFrame:
    """Orchestrate the feature engineering pipeline using pandas pipes."""
    if df.empty:
        return pd.DataFrame()
        
    df = (
        df.pipe(add_temporal_features)
          .pipe(add_lag_features)
          .pipe(add_rolling_features)
          .pipe(impute_lag_nans)
    )
    return df
