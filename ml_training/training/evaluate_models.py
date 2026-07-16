import os
import sys
import json
import datetime
import numpy as np
import pandas as pd
import joblib
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

# Add root folder to python path to access backend modules
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, project_root)

from ml_training.config import HORIZON_MODEL_PATHS, PROCESSED_DATA_DIR, METRICS_DIR, FEATURE_IMPORTANCE_DIR
from ml_training.features.validation import FEATURES

def main():
    test_path = os.path.join(PROCESSED_DATA_DIR, "test.pkl")
    print(f"Loading test set from {test_path}...", flush=True)
    if not os.path.exists(test_path):
        print(f"Error: Test set not found at {test_path}. Please run train_models.py first.", flush=True)
        sys.exit(1)
        
    df_test = joblib.load(test_path)
    print(f"Loaded test set with {len(df_test)} rows.", flush=True)
    
    horizons = ["1h", "3h", "6h", "12h", "24h"]
    
    for h in horizons:
        model_path = HORIZON_MODEL_PATHS[h]
        print(f"\nEvaluating model for {h} horizon...", flush=True)
        
        if not os.path.exists(model_path):
            print(f"Skipping horizon {h}: Model binary not found at {model_path}.", flush=True)
            continue
            
        model = joblib.load(model_path)
        target_col = f"target_aqi_{h}"
        
        # Drop rows where target_aqi_Xh is NaN in the test set
        df_test_horizon = df_test.dropna(subset=[target_col]).reset_index(drop=True)
        if len(df_test_horizon) == 0:
            print(f"Skipping horizon {h}: No valid test rows after target shifting.", flush=True)
            continue
            
        X_test = df_test_horizon[FEATURES]
        y_test = df_test_horizon[target_col]
        
        # Run predictions
        preds = model.predict(X_test)
        
        # Calculate metrics
        mae = mean_absolute_error(y_test, preds)
        rmse = np.sqrt(mean_squared_error(y_test, preds))
        r2 = r2_score(y_test, preds)
        
        metrics = {
            "horizon": h,
            "mae": float(mae),
            "rmse": float(rmse),
            "r2": float(r2),
            "test_rows": len(X_test),
            "evaluation_timestamp": datetime.datetime.utcnow().isoformat() + "Z"
        }
        
        # Save metrics to metrics/{horizon}_metrics.json
        metrics_path = os.path.join(METRICS_DIR, f"{h}_metrics.json")
        print(f"Saving metrics to {metrics_path}...", flush=True)
        with open(metrics_path, "w") as f:
            json.dump(metrics, f, indent=2)
            
        # Extract and sort feature importances
        importances = model.feature_importances_
        feature_importance_list = []
        for feat, imp in zip(FEATURES, importances):
            feature_importance_list.append({
                "feature": feat,
                "importance": float(imp)
            })
            
        # Sort descending by importance
        feature_importance_list = sorted(feature_importance_list, key=lambda x: x["importance"], reverse=True)
        
        # Save to feature_importance/{horizon}_feature_importance.json
        fi_path = os.path.join(FEATURE_IMPORTANCE_DIR, f"{h}_feature_importance.json")
        print(f"Saving feature importance to {fi_path}...", flush=True)
        with open(fi_path, "w") as f:
            json.dump(feature_importance_list, f, indent=2)
            
        print(f"{h} horizon evaluation completed successfully!", flush=True)
        
    print("\nAll model evaluations completed successfully!", flush=True)

if __name__ == "__main__":
    main()
