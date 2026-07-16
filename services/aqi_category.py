def get_aqi_category(aqi_value: float) -> str:
    """Classify AQI value into a standard US EPA category."""
    val = round(aqi_value)
    if val <= 50:
        return "Good"
    elif val <= 100:
        return "Moderate"
    elif val <= 150:
        return "Unhealthy for Sensitive Groups"
    elif val <= 200:
        return "Unhealthy"
    elif val <= 300:
        return "Very Unhealthy"
    else:
        return "Hazardous"

def get_us_aqi_category(aqi_value: float) -> str:
    """Classify AQI value into a standard US EPA category (maintained for compatibility)."""
    return get_aqi_category(aqi_value)
