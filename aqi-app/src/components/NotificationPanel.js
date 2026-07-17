import React from "react";
import "./NotificationPanel.css";

function NotificationPanel({

    aqi,

    safeTime,

    city,

    updatedAt

}) {

    const notifications = [];

    const getAQIColor = (value) => {

        if (value <= 50) return "#22c55e";

        if (value <= 100) return "#eab308";

        if (value <= 150) return "#f97316";

        if (value <= 200) return "#ef4444";

        if (value <= 300) return "#9333ea";

        return "#7f1d1d";

    };

    if (aqi > 150) {

        notifications.push({

            icon: "🚨",

            title: "High Pollution Alert",

            message: `AQI has reached ${aqi} in ${city}. Avoid prolonged outdoor activities and wear an N95 mask.`,

            color: "#ef4444"

        });

    }

    else if (aqi > 100) {

        notifications.push({

            icon: "⚠️",

            title: "Moderate Pollution",

            message: `AQI is ${aqi}. Sensitive groups should reduce outdoor exposure.`,

            color: "#f97316"

        });

    }

    else {

        notifications.push({

            icon: "🌿",

            title: "Good Air Quality",

            message: `AQI is ${aqi}. Outdoor activities are safe for most people.`,

            color: "#22c55e"

        });

    }

    notifications.push({

        icon: "🕒",

        title: "Safe Outdoor Window",

        message: safeTime || "Not Available",

        color: "#2563eb"

    });

    notifications.push({

        icon: "📍",

        title: "Current Location",

        message: city || "Unknown",

        color: "#0ea5e9"

    });

    notifications.push({

        icon: "⏰",

        title: "Last Updated",

        message: updatedAt || "Just now",

        color: "#8b5cf6"

    });

    if (notifications.length === 0) {

        return (

            <div className="notification-card">

                <h2>

                    🔔 Notifications

                </h2>

                <div className="empty-notification">

                    No notifications available.

                </div>

            </div>

        );

    }
        return (

        <div className="notification-card">

            <div className="notification-header">

                <h2>

                    🔔 Notifications

                </h2>

                <div className="notification-count">

                    {notifications.length}

                </div>

            </div>

            <div className="notification-list">

                {

                    notifications.map((item, index) => (

                        <div

                            key={index}

                            className="notification-item"

                        >

                            <div

                                className="notification-icon"

                                style={{

                                    background: item.color

                                }}

                            >

                                {item.icon}

                            </div>

                            <div className="notification-content">

                                <h3>

                                    {item.title}

                                </h3>

                                <p>

                                    {item.message}

                                </p>

                            </div>

                        </div>

                    ))

                }

            </div>

            <div className="notification-footer">

                <span>

                    Air Quality Notifications

                </span>

            </div>

        </div>

    );

}

export default NotificationPanel;