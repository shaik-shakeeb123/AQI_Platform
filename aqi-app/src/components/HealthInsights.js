import React from "react";
import "./HealthInsights.css";

const categoryMap = {
    "Good": {
        statusText: "🌿 Good Air Quality",
        color: "#22c55e",
        vulnerable: ["Everyone can safely enjoy outdoor activities"],
        important: "Air quality is excellent. Continue your normal daily routine."
    },
    "Moderate": {
        statusText: "🙂 Moderate Air Quality",
        color: "#f59e0b",
        vulnerable: ["Allergy Patients", "Asthma Patients"],
        important: "Most people are safe, but sensitive groups should be cautious."
    },
    "Unhealthy for Sensitive Groups": {
        statusText: "😷 Unhealthy for Sensitive Groups",
        color: "#f97316",
        vulnerable: ["Children", "Elderly", "Pregnant Women", "Asthma Patients"],
        important: "Sensitive groups should avoid long outdoor exposure."
    },
    "Unhealthy": {
        statusText: "⚠ Unhealthy Air Quality",
        color: "#ef4444",
        vulnerable: ["Children", "Elderly", "Pregnant Women", "Asthma Patients", "Heart Disease Patients", "Lung Disease Patients"],
        important: "Air pollution is high. Vulnerable groups should stay indoors."
    },
    "Very Unhealthy": {
        statusText: "⚠ Very Unhealthy Air Quality",
        color: "#a855f7",
        vulnerable: ["Children", "Elderly", "Pregnant Women", "Asthma Patients", "Heart/Lung Disease Patients"],
        important: "Air pollution is dangerous. Minimize outdoor activities."
    },
    "Hazardous": {
        statusText: "🚨 Hazardous Air Quality",
        color: "#7f1d1d",
        vulnerable: ["All population groups are affected"],
        important: "Emergency conditions. Avoid all outdoor activities."
    }
};

function HealthInsights({ aqi, healthInsights, loading, error }) {
    if (loading) {
        return (
            <div className="card health-card">
                <h2>🩺 Health Recommendations</h2>
                <div className="loading-text">Loading recommendations from backend...</div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="card health-card">
                <h2>🩺 Health Recommendations</h2>
                <div className="error-text">⚠ {error}</div>
            </div>
        );
    }

    if (!healthInsights) {
        return (
            <div className="card health-card">
                <h2>🩺 Health Recommendations</h2>
                <div className="loading-text">Awaiting telemetry...</div>
            </div>
        );
    }

    const { status, risk_level, recommendations, safety_warnings } = healthInsights;
    const presentation = categoryMap[status] || {
        statusText: `⚠ ${status} Air Quality`,
        color: "#6b7280",
        vulnerable: ["Vulnerable groups should exercise caution"],
        important: `Risk Level is evaluated as ${risk_level}.`
    };

    return (
        <div className="card health-card">
            <h2>🩺 Health Recommendations</h2>
            <div
                className="health-status"
                style={{
                    background: presentation.color
                }}
            >
                {presentation.statusText} (Risk: {risk_level})
            </div>

            <div className="health-section">
                <h4>⚠ Precautions & Warnings</h4>
                <ul>
                    {safety_warnings && safety_warnings.length > 0 ? (
                        safety_warnings.map((item, index) => (
                            <li key={index}>{item}</li>
                        ))
                    ) : (
                        <li>No specific precautions required.</li>
                    )}
                </ul>
            </div>

            <div className="health-section">
                <h4>✅ Recommended Actions</h4>
                <ul>
                    {recommendations && recommendations.length > 0 ? (
                        recommendations.map((item, index) => (
                            <li key={index}>{item}</li>
                        ))
                    ) : (
                        <li>Follow standard health advices.</li>
                    )}
                </ul>
            </div>

            <div className="health-section">
                <h4>👥 Vulnerable Groups Affected</h4>
                <ul>
                    {presentation.vulnerable.map((item, index) => (
                        <li key={index}>{item}</li>
                    ))}
                </ul>
            </div>

            <div className="important-box">
                <strong>Important</strong>
                <p>{presentation.important}</p>
            </div>
        </div>
    );
}

export default HealthInsights;