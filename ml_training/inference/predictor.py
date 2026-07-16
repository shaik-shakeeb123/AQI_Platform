import logging
import pandas as pd
from typing import List, Dict, Any, Optional, Tuple

from ml_training.features.preprocessing import run_preprocessing_pipeline
from ml_training.features.feature_engineering import run_feature_pipeline
from ml_training.features.validation import align_inference_features, validate_feature_dataframe

logger = logging.getLogger(__name__)

def calculate_us_sub_index(concentration: float, brackets: List[Tuple[float, float, float, float]], precision: Optional[int] = None) -> float:
    if precision is not None:
        concentration = round(concentration, precision)
    for c_low, c_high, i_low, i_high in brackets:
        if c_low <= concentration <= c_high:
            return ((i_high - i_low) / (c_high - c_low)) * (concentration - c_low) + i_low
    if concentration > brackets[-1][1]:
        return brackets[-1][3]
    return 0.0

def calculate_us_aqi_fallback(pm25: float, pm10: float) -> float:
    pm25_brackets = [
        (0.0, 12.0, 0.0, 50.0),
        (12.1, 35.4, 50.0, 100.0),
        (35.5, 55.4, 100.0, 150.0),
        (55.5, 150.4, 150.0, 200.0),
        (150.5, 250.4, 200.0, 300.0),
        (250.5, 350.4, 300.0, 400.0),
        (350.5, 500.0, 400.0, 500.0)
    ]
    pm10_brackets = [
        (0.0, 54.0, 0.0, 50.0),
        (54.1, 154.0, 50.0, 100.0),
        (154.1, 254.0, 100.0, 150.0),
        (254.1, 354.0, 150.0, 200.0),
        (354.1, 424.0, 200.0, 300.0),
        (424.1, 504.0, 300.0, 400.0),
        (504.1, 604.0, 400.0, 500.0)
    ]
    sub_pm25 = calculate_us_sub_index(pm25, pm25_brackets, precision=1)
    sub_pm10 = calculate_us_sub_index(pm10, pm10_brackets, precision=0)
    return max(sub_pm25, sub_pm10)

class MLPredictorService:
    """Manages raw feature transformations and runs model inference."""

    @staticmethod
    def predict_aqi(model: Any, history_data: List[Dict[str, Any]]) -> float:
        """Run AQI inference using the loaded LightGBM model.
        
        If no model is loaded, uses a fallback rule-based US EPA AQI approximation formula.
        """
        if not history_data:
            logger.warning("Empty history data received. Returning baseline AQI of 50.0.")
            return 50.0

        # Perform feature engineering via centralized functional pipeline
        try:
            # 1. Clean, resample, interpolate, and convert CO units
            preprocessed_df = run_preprocessing_pipeline(history_data)
            
            # 2. Extract lag and rolling window features
            engineered_df = run_feature_pipeline(preprocessed_df)
            
            # 3. Rename, validate, reorder, and select latest row
            features_df = align_inference_features(engineered_df)
            
            # If model is loaded, perform LightGBM inference
            if model is not None:
                # Validate column names and order
                validate_feature_dataframe(features_df)
                
                prediction = model.predict(features_df)
                if hasattr(prediction, "__len__"):
                    return float(prediction[0])
                return float(prediction)
        except Exception as ex:
            logger.error(f"Inference pipeline failed: {ex}. Dropping to fallback calculations.")

        # Fallback Calculation: US EPA AQI heuristic approximation
        latest_record = history_data[-1]
        pm25 = latest_record.get("pm25") or 25.0
        pm10 = latest_record.get("pm10") or 50.0
        
        predicted_aqi = calculate_us_aqi_fallback(pm25, pm10)
        logger.info(f"Fallback predictor output calculated: {predicted_aqi:.2f}")
        return float(predicted_aqi)
