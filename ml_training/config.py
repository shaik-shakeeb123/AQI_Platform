import os

# Base Directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))

# Processed Data Paths
PROCESSED_DATA_DIR = os.path.join(BASE_DIR, "data", "processed")

# Model Paths
MODEL_DIR = os.path.join(BASE_DIR, "models")
MODEL_V4_PATH = os.path.join(MODEL_DIR, "aqi_model_v4_clean.pkl")

# Horizon-specific Model Paths
HORIZON_MODEL_PATHS = {
    "1h": os.path.join(MODEL_DIR, "aqi_model_1h.pkl"),
    "3h": os.path.join(MODEL_DIR, "aqi_model_3h.pkl"),
    "6h": os.path.join(MODEL_DIR, "aqi_model_6h.pkl"),
    "12h": os.path.join(MODEL_DIR, "aqi_model_12h.pkl"),
    "24h": os.path.join(MODEL_DIR, "aqi_model_24h.pkl"),
}

# Metrics Directory
METRICS_DIR = os.path.join(BASE_DIR, "metrics")

# Feature Importance Directory
FEATURE_IMPORTANCE_DIR = os.path.join(BASE_DIR, "feature_importance")

# Ensure necessary directories exist
for d in [PROCESSED_DATA_DIR, MODEL_DIR, METRICS_DIR, FEATURE_IMPORTANCE_DIR]:
    os.makedirs(d, exist_ok=True)

