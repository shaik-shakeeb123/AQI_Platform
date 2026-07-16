from flask import Flask, request, jsonify
from flask_cors import CORS
import pandas as pd
from datetime import datetime
from collections import deque
from predictor import model_1h, model_3h, model_6h, model_12h, model_24h

app = Flask(__name__)
CORS(app)

pm25_history = deque(maxlen=6)
pm10_history = deque(maxlen=6)

def rolling_mean(values, window):
    vals = list(values)
    if not vals:
        return 0.0
    vals = vals[-window:]
    return sum(vals)/len(vals)

@app.route("/")
def home():
    return jsonify({"message":"AQI Insight Pro Prediction API Running"})

@app.route("/predict", methods=["POST"])
def predict():
    try:
        data = request.get_json()
        now = datetime.now()

        pm25 = float(data.get("pm25",0))
        pm10 = float(data.get("pm10",0))

        pm25_history.append(pm25)
        pm10_history.append(pm10)

        features = pd.DataFrame([{
            "pm25": pm25,
            "pm10": pm10,
            "co": float(data.get("co",0)),
            "no2": float(data.get("no2",0)),
            "so2": float(data.get("so2",0)),
            "o3": float(data.get("o3",0)),
            "temperature": float(data.get("temperature",0)),
            "humidity": float(data.get("humidity",0)),
            "wind_speed": float(data.get("wind_speed",0)),
            "wind_direction": float(data.get("wind_direction",0)),
            "pressure": float(data.get("pressure",0)),
            "precipitation": float(data.get("precipitation",0)),
            "hour": now.hour,
            "day_of_week": now.weekday(),
            "pm25_lag_1": pm25_history[-2] if len(pm25_history)>=2 else pm25,
            "pm25_lag_3": pm25_history[-4] if len(pm25_history)>=4 else pm25,
            "pm10_lag_1": pm10_history[-2] if len(pm10_history)>=2 else pm10,
            "pm25_roll_mean_3": rolling_mean(pm25_history,3),
            "pm10_roll_mean_3": rolling_mean(pm10_history,3),
            "pm25_roll_mean_6": rolling_mean(pm25_history,6)
        }])

        predictions = {
            "1h": round(float(model_1h.predict(features)[0]),2),
            "3h": round(float(model_3h.predict(features)[0]),2),
            "6h": round(float(model_6h.predict(features)[0]),2),
            "12h": round(float(model_12h.predict(features)[0]),2),
            "24h": round(float(model_24h.predict(features)[0]),2)
        }

        return jsonify({
            "success": True,
            "predictions": predictions,
            "history": {
                "pm25": list(pm25_history),
                "pm10": list(pm10_history)
            }
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == "__main__":
    import os
    port = int(os.environ.get("FLASK_PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
