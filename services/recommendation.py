from typing import List, Tuple

def get_health_insights_recommendations(status: str) -> Tuple[str, List[str], List[str]]:
    """Determine risk level, recommendations, and safety warnings based on US EPA category status."""
    if status == "Good":
        risk_level = "Low"
        recommendations = ["Air quality is clean. Ideal for outdoor exercises."]
        safety_warnings = ["None"]
    elif status == "Moderate":
        risk_level = "Moderate"
        recommendations = ["Acceptable air quality; however, sensitive individuals should monitor symptoms."]
        safety_warnings = ["Asthmatics should keep inhaler nearby."]
    elif status == "Unhealthy for Sensitive Groups":
        risk_level = "Moderate"
        recommendations = ["Sensitive individuals should reduce heavy outdoor activities."]
        safety_warnings = ["Asthmatics should keep inhaler nearby."]
    elif status == "Unhealthy":
        risk_level = "High"
        recommendations = ["Avoid prolonged outdoor workouts. Wear mask if outside."]
        safety_warnings = ["Vulnerable groups should stay indoors."]
    elif status == "Very Unhealthy":
        risk_level = "High"
        recommendations = ["Stay indoors as much as possible. Wear N95 mask."]
        safety_warnings = ["Vulnerable individuals should use air purifiers."]
    else:
        risk_level = "Critical"
        recommendations = ["Remain indoors. Avoid all physical outdoor activities."]
        safety_warnings = ["Critical health hazards for all age groups."]
    return risk_level, recommendations, safety_warnings

def get_safe_window_recommendations(category: str) -> List[str]:
    """Get safety and cardio exercise recommendations based on US EPA category."""
    if category == "Good":
        return [
            "Air quality is excellent.",
            "Highly recommended for outdoor exercise, cycling, and running."
        ]
    elif category == "Moderate":
        return [
            "Air quality is moderate.",
            "Acceptable air quality; however, sensitive individuals should monitor symptoms."
        ]
    elif category == "Unhealthy for Sensitive Groups":
        return [
            "Air quality is unhealthy for sensitive groups.",
            "Sensitive individuals (elderly, children, asthmatics) should limit prolonged outdoor exertion."
        ]
    elif category == "Unhealthy":
        return [
            "Air quality is unhealthy.",
            "Everyone may begin to experience health effects; members of sensitive groups may experience more serious health effects."
        ]
    elif category == "Very Unhealthy":
        return [
            "Air quality is very unhealthy.",
            "Health alert: everyone may experience more serious health effects. Stay indoors."
        ]
    else:
        return [
            "Air quality is hazardous.",
            "Health warnings of emergency conditions. The entire population is more likely to be affected."
        ]

def get_exposure_suggestions(health_concern_level: str) -> List[str]:
    """Determine suggestions based on US EPA category level."""
    if health_concern_level == "Good":
        return ["Air exposure risk is minimal. Safe for general population."]
    elif health_concern_level == "Moderate":
        return ["Safe for outdoor activities. Minor exposure risk for sensitive groups."]
    elif health_concern_level == "Unhealthy for Sensitive Groups":
        return ["Limit prolonged outdoor exertion if experiencing symptoms."]
    else:
        return ["Limit outdoor exposure. Consider using air purifiers indoors."]
