import React from "react";
import "./AQICard.css";

function AQICard({ aqi, data, updatedAt }) {

    const ranges = [

        {
            min: 0,
            max: 50,
            status: "Good",
            color: "#22c55e"
        },

        {
            min: 51,
            max: 100,
            status: "Moderate",
            color: "#eab308"
        },

        {
            min: 101,
            max: 150,
            status: "Sensitive",
            color: "#f97316"
        },

        {
            min: 151,
            max: 200,
            status: "Unhealthy",
            color: "#ef4444"
        },

        {
            min: 201,
            max: 300,
            status: "Very Unhealthy",
            color: "#9333ea"
        },

        {
            min: 301,
            max: 500,
            status: "Hazardous",
            color: "#7f1d1d"
        }

    ];

    if (aqi === null || aqi === undefined) {

        return (

            <div className="card aqi-card">

                <h3>🌍 Current AQI</h3>

                <div
                    style={{
                        textAlign: "center",
                        padding: "60px 0",
                        fontSize: "22px"
                    }}
                >
                    Loading AQI...
                </div>

            </div>

        );

    }

    const currentRange = ranges.find(

        item => aqi >= item.min && aqi <= item.max

    );

    const status = currentRange?.status || "Unknown";

    const color = currentRange?.color || "#38bdf8";

    return (

        <div className="card aqi-card">

            <h3>

                🌍 Current AQI

            </h3>

            <h1
                style={{
                    color: color
                }}
            >

                {aqi}

            </h1>

            <div

                className="badge"

                style={{

                    background: color

                }}

            >

                {status}

            </div>

            <div className="aqi-info">

                <p>

                    <strong>

                        🌫 Main Pollutant

                    </strong>

                    <span>

                        {data?.dominentpol || "N/A"}

                    </span>

                </p>

                <p>

                    <strong>

                        ⚠ Risk Level

                    </strong>

                    <span>

                        {status}

                    </span>

                </p>

                <p>

                    <strong>

                        📍 Station

                    </strong>

                    <span>

                        {data?.city?.name || "Unknown"}

                    </span>

                </p>

                <p>

                    <strong>

                        🕒 Updated

                    </strong>

                    <span>

                        {updatedAt || "--"}

                    </span>

                </p>

            </div>

            <h4 className="meter-title">

                AQI Scale

            </h4>

            <div className="aqi-meter">

                {

                    ranges.map((item, index) => (

                        <div

                            key={index}

                            className="meter-item"

                        >

                            <span

                                className="meter-label"

                                style={{

                                    color:

                                        item === currentRange

                                            ? item.color

                                            : "var(--secondary)",

                                    fontWeight:

                                        item === currentRange

                                            ? "700"

                                            : "500"

                                }}

                            >

                                {item.status}

                            </span>

                            <div

                                className="meter-segment"

                                style={{

                                    background: item.color,

                                    opacity:

                                        item === currentRange

                                            ? 1

                                            : 0.35

                                }}

                            >

                                {

                                    item.max === 500

                                        ? `${item.min}+`

                                        : `${item.min}-${item.max}`

                                }

                            </div>

                        </div>

                    ))

                }

            </div>

            <div

                className="meter-status"

                style={{

                    color: color

                }}

            >

                ▲ Current AQI Range : <strong>{status}</strong>

            </div>

        </div>

    );

}

export default AQICard;