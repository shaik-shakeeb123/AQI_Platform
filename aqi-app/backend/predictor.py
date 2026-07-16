import os
import joblib

# ==============================
# Models Folder
# ==============================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE_DIR, "models")

# ==============================
# Load Models
# ==============================

try:

    model_1h = joblib.load(
        os.path.join(MODEL_DIR, "aqi_model_1h.pkl")
    )

    model_3h = joblib.load(
        os.path.join(MODEL_DIR, "aqi_model_3h.pkl")
    )

    model_6h = joblib.load(
        os.path.join(MODEL_DIR, "aqi_model_6h.pkl")
    )

    model_12h = joblib.load(
        os.path.join(MODEL_DIR, "aqi_model_12h.pkl")
    )

    model_24h = joblib.load(
        os.path.join(MODEL_DIR, "aqi_model_24h.pkl")
    )

    print("\n====================================")
    print("✅ All AQI Models Loaded Successfully")
    print("====================================")

except Exception as e:

    print("\n====================================")
    print("❌ Model Loading Failed")
    print("====================================")
    print(e)