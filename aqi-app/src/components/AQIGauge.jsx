import React from "react";
import "./AQIGauge.css";

function AQIGauge({ aqi, exposureData, loading, error }) {
    if (loading) {
        return (
            <div className="card gauge-card">
                <h2>🌡 AQI Exposure</h2>
                <div className="loading-text" style={{ padding: "40px 0", textAlign: "center" }}>
                    Loading AI Exposure Analytics...
                </div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="card gauge-card">
                <h2>🌡 AQI Exposure</h2>
                <div className="loading-text" style={{ padding: "40px 0", textAlign: "center", color: "#ef4444" }}>
                    ⚠️ {error}
                </div>
            </div>
        );
    }

    if (!exposureData) {
        return (
            <div className="card gauge-card">
                <h2>🌡 AQI Exposure</h2>
                <div className="loading-text" style={{ padding: "40px 0", textAlign: "center" }}>
                    Exposure Analytics Unavailable
                </div>
            </div>
        );
    }

    const {
        exposure_safety_score: exposureScore,
        lungs,
        heart,
        eyes,
        exercise,
        outdoor,
        mask,
        recovery_tips: tips = []
    } = exposureData;

    // Preserve exact original UI coloring rules based on aqi
    let color = "#22c55e";
    if (aqi <= 50) {
        color = "#22c55e";
    } else if (aqi <= 100) {
        color = "#eab308";
    } else if (aqi <= 150) {
        color = "#f97316";
    } else if (aqi <= 200) {
        color = "#ef4444";
    } else {
        color = "#7f1d1d";
    }

    return (
        <div className="card gauge-card">
            <h2>
                🌡 AQI Exposure 
            </h2>

            <div
                className="gauge-score"
                style={{
                    background: color
                }}
            >
                <h1>
                    {exposureScore}/100
                </h1>
                <p>
                    Exposure Score
                </p>
            </div>

            <div className="organ-grid">
                <div className="organ-card">
                    🫁
                    <h3>Lungs</h3>
                    <p>{lungs}</p>
                </div>

                <div className="organ-card">
                    ❤️
                    <h3>Heart</h3>
                    <p>{heart}</p>
                </div>

                <div className="organ-card">
                    👁
                    <h3>Eyes</h3>
                    <p>{eyes}</p>
                </div>

                <div className="organ-card">
                    🏃
                    <h3>Exercise</h3>
                    <p>{exercise}</p>
                </div>
            </div>

            <div className="info-box">
                <strong>
                    ⏳ Maximum Outdoor Exposure
                </strong>
                <p>{outdoor}</p>
            </div>

            {/* <div className="info-box">
                <strong>
                    😷 Mask Recommendation
                </strong>
                <p>{mask}</p>
            </div>  */}

            <div className="tips-box">
                <h3>
                    🌱 Recovery Tips
                </h3>
                <ul>
                    {
                        tips.map((tip, index) => (
                            <li key={index}>
                                {tip}
                            </li>
                        ))
                    }
                </ul>
            </div>
        </div>
    );
}

export default AQIGauge;