import joblib
import pandas as pd
from datetime import datetime

# ==========================
# Load Models
# ==========================

model_1h = joblib.load("D:\PSNM\aqi-app\AI MODELS\aqi_model_1h.pkl")
model_3h = joblib.load("D:\PSNM\aqi-app\AI MODELS\aqi_model_3h.pkl")
model_6h = joblib.load("D:\PSNM\aqi-app\AI MODELS\aqi_model_6h.pkl")
model_12h = joblib.load("D:\PSNM\aqi-app\AI MODELS\aqi_model_12h.pkl")
model_24h = joblib.load("D:\PSNM\aqi-app\AI MODELS\aqi_model_24h.pkl")


# ==========================
# Prediction Function
# ==========================

def predict_aqi(
    pm25,
    pm10,
    co,
    no2,
    so2,
    o3,
    temperature,
    humidity,
    wind_speed,
    wind_direction,
    pressure,
    precipitation,
    pm25_lag_1,
    pm25_lag_3,
    pm10_lag_1,
    pm25_roll_mean_3,
    pm10_roll_mean_3,
    pm25_roll_mean_6,
):

    now = datetime.now()

    hour = now.hour
    day_of_week = now.weekday()

    features = pd.DataFrame([{

        "pm25": pm25,
        "pm10": pm10,
        "co": co,
        "no2": no2,
        "so2": so2,
        "o3": o3,
        "temperature": temperature,
        "humidity": humidity,
        "wind_speed": wind_speed,
        "wind_direction": wind_direction,
        "pressure": pressure,
        "precipitation": precipitation,
        "hour": hour,
        "day_of_week": day_of_week,
        "pm25_lag_1": pm25_lag_1,
        "pm25_lag_3": pm25_lag_3,
        "pm10_lag_1": pm10_lag_1,
        "pm25_roll_mean_3": pm25_roll_mean_3,
        "pm10_roll_mean_3": pm10_roll_mean_3,
        "pm25_roll_mean_6": pm25_roll_mean_6

    }])

    predictions = {

        "1 Hour": float(model_1h.predict(features)[0]),
        "3 Hours": float(model_3h.predict(features)[0]),
        "6 Hours": float(model_6h.predict(features)[0]),
        "12 Hours": float(model_12h.predict(features)[0]),
        "24 Hours": float(model_24h.predict(features)[0]),

    }

    return predictions