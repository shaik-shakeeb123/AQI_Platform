import os
import sys
import json
import datetime
import pandas as pd
import joblib
from lightgbm import LGBMRegressor

# Add root folder to python path to access backend modules
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, project_root)

from ml_training.config import HORIZON_MODEL_PATHS, PROCESSED_DATA_DIR, MODEL_DIR
from ml_training.features.preprocessing import resample_and_interpolate_segments
from ml_training.features.feature_engineering import run_feature_pipeline
from ml_training.features.targets import generate_training_targets
from ml_training.features.validation import FEATURES

CSV_TO_CANONICAL_MAP = {
    "PM2_5_ugm3": "pm25",
    "PM10_ugm3": "pm10",
    "CO_ugm3": "co",
    "NO2_ugm3": "no2",
    "SO2_ugm3": "so2",
    "O3_ugm3": "o3",
    "Temp_2m_C": "temperature",
    "Humidity_Percent": "humidity",
    "Wind_Speed_10m_kmh": "wind_speed",
    "Wind_Dir_10m": "wind_direction",
    "Pressure_MSL_hPa": "pressure",
    "Precipitation_mm": "precipitation",
    "US_AQI": "aqi",
    "Datetime": "recorded_at",
    "City": "city",
    "State": "state",
    "Latitude": "latitude",
    "Longitude": "longitude"
}

def load_local_csv_dataset() -> pd.DataFrame:
    """Load the India AQI local complete dataset CSV."""
    csv_path = os.path.join(project_root, "ml_training", "INDIA_AQI_COMPLETE_20251126.csv")
    print(f"Loading local dataset CSV from {csv_path}...", flush=True)
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Required training source dataset not found at: {csv_path}")
    df = pd.read_csv(csv_path)
    print(f"Loaded {len(df)} records from CSV.", flush=True)
    return df

def engineer_features_and_targets(df: pd.DataFrame) -> pd.DataFrame:
    """Group by city and engineer time-series lag, rolling, and horizon target variables."""
    print("Performing feature engineering on canonical lowercase schema...", flush=True)
    
    # 1. Alias city as location_name to align with resample_and_interpolate_segments requirements
    df["location_name"] = df["City"]
    
    # 2. Rename cased CSV headers directly to the canonical lowercase schema
    df = df.rename(columns=CSV_TO_CANONICAL_MAP)
    
    # 3. Handle CO unit scaling: the CSV stores CO_ugm3 in ug/m3. The centralized preprocessing
    # pipeline expects co to be in mg/m3 (and converts it to ug/m3). We divide by 1000.0 here
    # to perfectly align inputs and avoid servable pipeline deviations.
    if "co" in df.columns:
        df["co"] = df["co"] / 1000.0
        
    df["timestamp"] = pd.to_datetime(df["recorded_at"])
    
    processed_groups = []
    
    # Group by location (city) to calculate lag/rolling metrics chronologically
    for name, group in df.groupby("location_name"):
        if len(group) == 0:
            continue
            
        # Resample and interpolate contiguous segments
        resampled_group = resample_and_interpolate_segments(group, gap_threshold_hours=12.0, interpolation_limit_hours=3)
        if resampled_group.empty:
            continue
            
        # Sort group chronologically
        group = resampled_group.sort_values("timestamp").reset_index(drop=True)
        
        # Run feature pipeline (lags, rolling averages, temporal properties, lag NaN fills)
        group = run_feature_pipeline(group)
        
        # Generate target columns for all forecast horizons (target_aqi_1h, target_aqi_3h, etc.)
        group = generate_training_targets(group)
        
        processed_groups.append(group)
        
    if not processed_groups:
        return pd.DataFrame()
        
    df_out = pd.concat(processed_groups, ignore_index=True)
    return df_out

def main():
    try:
        df = load_local_csv_dataset()
    except Exception as e:
        print(f"Error loading dataset: {e}", flush=True)
        sys.exit(1)
        
    df_processed = engineer_features_and_targets(df)
    if df_processed.empty:
        print("Error: Post-processed dataset is empty.", flush=True)
        sys.exit(1)
        
    print(f"Processed dataset size: {len(df_processed)} rows.", flush=True)
    
    # Sort chronologically globally for proper train/test splitting
    df_processed = df_processed.sort_values("timestamp").reset_index(drop=True)
    
    # Split execution (Option C): Split globally at '2025-03-30 00:00:00'
    split_date = pd.to_datetime("2025-03-30 00:00:00")
    print(f"Splitting dataset globally at calendar boundary: {split_date}", flush=True)
    
    df_train = df_processed[df_processed["timestamp"] < split_date].reset_index(drop=True)
    df_test = df_processed[df_processed["timestamp"] >= split_date].reset_index(drop=True)
    
    # Save datasets to data/processed/train.pkl and test.pkl
    train_path = os.path.join(PROCESSED_DATA_DIR, "train.pkl")
    test_path = os.path.join(PROCESSED_DATA_DIR, "test.pkl")
    
    print(f"Saving train split ({len(df_train)} rows) to {train_path}...", flush=True)
    joblib.dump(df_train, train_path)
    
    print(f"Saving test split ({len(df_test)} rows) to {test_path}...", flush=True)
    joblib.dump(df_test, test_path)
    
    # Train separate models for each prediction horizon
    horizons = ["1h", "3h", "6h", "12h", "24h"]
    
    for h in horizons:
        target_col = f"target_aqi_{h}"
        print(f"\nTraining model for {h} horizon...", flush=True)
        
        # Drop rows where target_aqi_Xh is NaN in the training set
        df_train_horizon = df_train.dropna(subset=[target_col]).reset_index(drop=True)
        if len(df_train_horizon) == 0:
            print(f"Skipping horizon {h}: No valid training rows after target shifting.", flush=True)
            continue
            
        X_train = df_train_horizon[FEATURES]
        y_train = df_train_horizon[target_col]
        
        # Configure and train LightGBM Regressor
        model = LGBMRegressor(
            n_estimators=100,
            learning_rate=0.05,
            random_state=42,
            n_jobs=-1
        )
        
        model.fit(
            X_train, 
            y_train
        )
        
        # Save model binary
        model_path = HORIZON_MODEL_PATHS[h]
        print(f"Saving trained model binary to {model_path}...", flush=True)
        joblib.dump(model, model_path)
        
        # Save metadata json
        metadata_path = os.path.join(MODEL_DIR, f"aqi_model_{h}_metadata.json")
        metadata = {
            "dataset": "INDIA_AQI_COMPLETE_20251126.csv",
            "horizon": h,
            "training_timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "row_count": len(X_train),
            "feature_count": len(FEATURES),
            "feature_names": FEATURES,
            "model_type": "LightGBM"
        }
        
        print(f"Saving metadata to {metadata_path}...", flush=True)
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)
            
        print(f"{h} horizon model training and persistence completed successfully!", flush=True)
        
    print("\nAll multi-horizon models trained successfully!", flush=True)

if __name__ == "__main__":
    main()
