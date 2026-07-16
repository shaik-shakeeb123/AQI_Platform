import pandas as pd
from typing import List

FEATURES = [
    "pm25",
    "pm10",
    "co",
    "no2",
    "so2",
    "o3",
    "temperature",
    "humidity",
    "wind_speed",
    "wind_direction",
    "pressure",
    "precipitation",
    "hour",
    "day_of_week",
    "pm25_lag_1",
    "pm25_lag_3",
    "pm10_lag_1",
    "pm25_roll_mean_3",
    "pm10_roll_mean_3",
    "pm25_roll_mean_6"
]

# Default values mapping canonical feature names to fallbacks
FEATURE_DEFAULTS = {
    "pm25": 25.0,
    "pm10": 50.0,
    "no2": 20.0,
    "o3": 30.0,
    "co": 500.0,
    "so2": 10.0,
    "temperature": 25.0,
    "humidity": 60.0,
    "wind_speed": 2.0,
    "wind_direction": 180.0,
    "pressure": 1013.0,
    "precipitation": 0.0,
    "hour": 12,
    "day_of_week": 0,
    "pm25_lag_1": 25.0,
    "pm25_lag_3": 25.0,
    "pm10_lag_1": 50.0,
    "pm25_roll_mean_3": 25.0,
    "pm10_roll_mean_3": 50.0,
    "pm25_roll_mean_6": 25.0
}

def validate_feature_dataframe(df: pd.DataFrame) -> None:
    """Validate that the features DataFrame matches the training feature set exactly in name and order."""
    if list(df.columns) != FEATURES:
        raise ValueError(
            f"Feature columns mismatch!\n"
            f"Expected: {FEATURES}\n"
            f"Got: {list(df.columns)}"
        )

def align_inference_features(df: pd.DataFrame) -> pd.DataFrame:
    """Inject missing columns, reorder, and select latest row using lowercase canonical schema."""
    df = df.copy()
    
    # Grab the latest row for live inference
    df = df.tail(1).copy()
    
    # Ensure all required features exist
    for col in FEATURES:
        if col not in df.columns:
            df[col] = FEATURE_DEFAULTS.get(col, 0.0)
            
    # Filter and reorder columns
    df = df[FEATURES]
    return df
