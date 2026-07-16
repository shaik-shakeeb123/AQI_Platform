import os
import sys
import json

# Add root folder to python path to access backend modules
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, project_root)

from ml_training.config import METRICS_DIR, FEATURE_IMPORTANCE_DIR

def main():
    horizons = ["1h", "3h", "6h", "12h", "24h"]
    
    table_lines = []
    table_lines.append("| Horizon | MAE | RMSE | R² | Top 3 Features |")
    table_lines.append("| :--- | :--- | :--- | :--- | :--- |")
    
    found_any = False
    
    for h in horizons:
        metrics_path = os.path.join(METRICS_DIR, f"{h}_metrics.json")
        fi_path = os.path.join(FEATURE_IMPORTANCE_DIR, f"{h}_feature_importance.json")
        
        if not os.path.exists(metrics_path):
            continue
            
        found_any = True
        
        # Load metrics
        with open(metrics_path, "r") as f:
            metrics = json.load(f)
            
        # Load top features
        top_features_str = "N/A"
        if os.path.exists(fi_path):
            with open(fi_path, "r") as f:
                fi_list = json.load(f)
            if fi_list:
                # Get top 3 feature names
                top_3 = [item["feature"] for item in fi_list[:3]]
                top_features_str = ", ".join(top_3)
                
        mae = metrics.get("mae", 0.0)
        rmse = metrics.get("rmse", 0.0)
        r2 = metrics.get("r2", 0.0)
        
        table_lines.append(f"| {h} | {mae:.4f} | {rmse:.4f} | {r2:.4f} | {top_features_str} |")
        
    if not found_any:
        print("No evaluation metrics found. Please run evaluate_models.py first.", flush=True)
        return
        
    print("\nConsolidated Model Comparison Table:\n", flush=True)
    print("\n".join(table_lines), flush=True)
    print("\n", flush=True)

if __name__ == "__main__":
    main()
