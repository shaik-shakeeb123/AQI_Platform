import React, { useEffect, useState } from "react";
import "./AlertPanel.css";

function AlertPanel({ aqi }) {

    const [visible, setVisible] = useState(true);

    useEffect(() => {

        setVisible(true);

    }, [aqi]);

    useEffect(() => {

        if (aqi <= 100) {

            const timer = setTimeout(() => {

                setVisible(false);

            }, 7000);

            return () => clearTimeout(timer);

        }

    }, [aqi]);

    if (aqi === null || aqi === undefined || !visible) {

        return null;

    }

    let title = "";
    let message = "";
    let color = "";
    let icon = "";

    if (aqi <= 50) {

        title = "🌿 Good Air Quality";

        message =
            "The air quality is excellent. Outdoor conditions are safe for everyone.";

        color = "#22c55e";

        icon = "🌿";

    }

    else if (aqi <= 100) {

        title = "🙂 Moderate Air Quality";

        message =
            "Air quality is acceptable. Most people can continue normal outdoor activities.";

        color = "#eab308";

        icon = "🙂";

    }

    else if (aqi <= 150) {

        title = "🟠 Unhealthy for Sensitive Groups";

        message =
            "Air pollution has increased. Sensitive groups should be cautious.";

        color = "#f97316";

        icon = "😷";

    }

    else if (aqi <= 200) {

        title = "🔴 Unhealthy Air Quality";

        message =
            "Air quality is unhealthy. Pollution levels are high.";

        color = "#ef4444";

        icon = "🚨";

    }

    else if (aqi <= 300) {

        title = "🟣 Very Unhealthy";

        message =
            "Air pollution has reached a very unhealthy level.";

        color = "#9333ea";

        icon = "⚠️";

    }

    else {

        title = "⚫ Hazardous Air Quality";

        message =
            "Hazardous pollution detected. Air quality has reached emergency levels.";

        color = "#7f1d1d";

        icon = "☠️";

    }

    return (

        <div

            className="alert-panel"

            style={{

                borderLeft: `8px solid ${color}`

            }}

        >

            <button

                className="alert-close"

                onClick={() => setVisible(false)}

            >

                ✕

            </button>

            <div

                className="alert-icon"

                style={{

                    background: color

                }}

            >

                {icon}

            </div>

            <div className="alert-content">

                <h2>

                    {title}

                </h2>

                <p>

                    {message}

                </p>

                <div className="aqi-badge">

                    Current AQI&nbsp;

                    <strong>

                        {aqi}

                    </strong>

                </div>

            </div>

        </div>

    );

}

export default AlertPanel;