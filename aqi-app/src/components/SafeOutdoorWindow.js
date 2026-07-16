import React from "react";
import { useAuth } from "../context/AuthContext";
import "./SafeOutdoorWindow.css";

const safetyColors = {
    "Good": "#22c55e",
    "Moderate": "#f59e0b",
    "Unhealthy for Sensitive Groups": "#f97316",
    "Unhealthy": "#ef4444",
    "Very Unhealthy": "#a855f7",
    "Hazardous": "#7f1d1d"
};

function SafeOutdoorWindow({ aqi, safeWindow, loading, error }) {
    const { user, loading: userLoading } = useAuth();

    const userData = user ? {
        ageGroup: user.age_group || "Adult",
        activity: user.outdoor_activity || "Moderate",
        city: user.city || "",
        health: user.health_conditions || []
    } : null;

    if (loading || userLoading) {
        return (
            <div className="card safe-card">
                <h2>🌤 Safe Outdoor Window</h2>
                <div className="loading-text">Calculating safe outdoor window...</div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="card safe-card">
                <h2>🌤 Safe Outdoor Window</h2>
                <div className="error-text">⚠ {error}</div>
            </div>
        );
    }

    if (!safeWindow) {
        return (
            <div className="card safe-card">
                <h2>🌤 Safe Outdoor Window</h2>
                <div className="loading-text">Awaiting telemetry...</div>
            </div>
        );
    }

    const age = userData?.ageGroup || "Adult";
    const activity = userData?.activity || "Moderate";
    const health = userData?.health || [];

    const { safe_window_start, safe_window_end, predicted_aqi, safety_level, recommendations } = safeWindow;
    
    // Format window time range
    let timeStr = "";
    try {
        const start = new Date(safe_window_start);
        const end = new Date(safe_window_end);
        const formatTime = (date) => date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        
        // If window is restricted (e.g. Hazardous stay indoors)
        if (safety_level === "Hazardous") {
            timeStr = "Stay Indoors";
        } else if (safety_level === "Very Unhealthy") {
            timeStr = "Indoor activities preferred";
        } else {
            timeStr = `${formatTime(start)} - ${formatTime(end)}`;
        }
    } catch (e) {
        timeStr = "Calculated window unavailable";
    }

    const color = safetyColors[safety_level] || "#6b7280";
    
    // Evaluate personalized advices using backend predicted AQI
    let ageAdvice = "";
    if (age === "Child") {
        ageAdvice = predicted_aqi <= 100 ? "Outdoor play is safe." : "Limit outdoor play.";
    } else if (age === "Senior Citizen") {
        ageAdvice = predicted_aqi <= 50 ? "Morning walks are recommended." : "Stay indoors whenever possible.";
    } else {
        ageAdvice = "Follow normal precautions.";
    }

    let activityAdvice = "";
    if (activity === "High") {
        activityAdvice = predicted_aqi <= 100 ? "Running and cycling are safe." : "Prefer light exercise.";
    } else if (activity === "Low") {
        activityAdvice = "Short walks are recommended.";
    } else {
        activityAdvice = "Walking and yoga are ideal.";
    }

    const mask = predicted_aqi > 100 || (predicted_aqi > 50 && (health.includes("Asthma") || health.includes("Allergy")));

    return (
        <div className="card safe-card">
            <h2>🌤 Safe Outdoor Window</h2>
            <div
                className="safe-status"
                style={{
                    background: color
                }}
            >
                {safety_level} (Forecasted AQI: {predicted_aqi})
            </div>

            <div className="safe-section">
                <h3>🕒 Recommended Time Window</h3>
                <p>{timeStr}</p>
            </div>

            <div className="safe-section">
                <h3>👤 Personalized Recommendations</h3>
                <ul>
                    {recommendations.map((rec, index) => (
                        <li key={index}>{rec}</li>
                    ))}
                </ul>
            </div>

            <div className="safe-section">
                <h3>🎂 Age Group ({age})</h3>
                <p>{ageAdvice}</p>
            </div>

            <div className="safe-section">
                <h3>🏃 Activity Recommendation</h3>
                <p>{activityAdvice}</p>
            </div>

            <div className="safe-section">
                <h3>😷 Mask Recommendation</h3>
                <p>{mask ? "Recommended" : "Not Required"}</p>
            </div>

            {health.length > 0 && (
                <div className="safe-section">
                    <h3>⚠ Registered Health Conditions</h3>
                    <ul>
                        {health.map((item, index) => (
                            <li key={index}>{item}</li>
                        ))}
                    </ul>
                </div>
            )}

            <div className="safe-tip">
                💡 Stay hydrated and check AQI regularly before outdoor activities.
            </div>
        </div>
    );
}

export default SafeOutdoorWindow;