import pandas as pd

def generate_training_targets(df: pd.DataFrame) -> pd.DataFrame:
    """Generate horizon-specific target labels by shifting the canonical aqi column chronologically.
    
    This is executed at training time per station.
    """
    df = df.copy()
    if "aqi" not in df.columns:
        raise ValueError("AQI column ('aqi') must be present to compute target labels.")
        
    df["target_aqi_1h"] = df["aqi"].shift(-1)
    df["target_aqi_3h"] = df["aqi"].shift(-3)
    df["target_aqi_6h"] = df["aqi"].shift(-6)
    df["target_aqi_12h"] = df["aqi"].shift(-12)
    df["target_aqi_24h"] = df["aqi"].shift(-24)
    return df
