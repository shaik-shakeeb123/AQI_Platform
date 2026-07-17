import React from "react";
import "./TopPollutant.css";

function TopPollutant({ data }) {

    if (!data || !data.iaqi) {
        return (
            <div className="top-pollutant-card">

                <h2>🌬 Top Pollutant</h2>

                <div className="loading-text">
                    Loading pollutant data...
                </div>

            </div>
        );
    }

    const pollutantInfo = {

        pm25: {
            name: "PM2.5",
            reason: "Fine particles produced by vehicles, industries and dust.",
            impact: "Can penetrate deep into the lungs and may cause respiratory problems."
        },

        pm10: {
            name: "PM10",
            reason: "Road dust, construction activities and industrial emissions.",
            impact: "May irritate the eyes, nose and throat."
        },

        o3: {
            name: "Ozone",
            reason: "Formed by sunlight reacting with pollutants.",
            impact: "May cause coughing and breathing discomfort."
        },

        no2: {
            name: "Nitrogen Dioxide",
            reason: "Vehicle exhaust and industrial emissions.",
            impact: "Can worsen asthma and lung diseases."
        },

        so2: {
            name: "Sulphur Dioxide",
            reason: "Burning coal and industrial activities.",
            impact: "Can irritate the respiratory system."
        },

        co: {
            name: "Carbon Monoxide",
            reason: "Incomplete fuel combustion.",
            impact: "Reduces oxygen delivery throughout the body."
        }

    };

    const pollutantKeys = [

        "pm25",
        "pm10",
        "o3",
        "no2",
        "so2",
        "co"

    ];

    let highestKey = null;
    let highestValue = -1;

    pollutantKeys.forEach((key) => {

        const value = data.iaqi[key]?.v;

        if (value !== undefined && value > highestValue) {

            highestValue = value;
            highestKey = key;

        }

    });

    if (!highestKey) {

        return (
            <div className="top-pollutant-card">

                <h2>🌬 Top Pollutant</h2>

                <div className="loading-text">

                    Pollutant information unavailable.

                </div>

            </div>
        );

    }

    const pollutant = pollutantInfo[highestKey];

    const value = highestValue;

    const getStatus = () => {

        if (value <= 50) {

            return {

                text: "Good",

                color: "#22c55e"

            };

        }

        if (value <= 100) {

            return {

                text: "Moderate",

                color: "#eab308"

            };

        }

        if (value <= 150) {

            return {

                text: "USG",

                color: "#f97316"

            };

        }

        if (value <= 200) {

            return {

                text: "Unhealthy",

                color: "#ef4444"

            };

        }

        if (value <= 300) {

            return {

                text: "Very Unhealthy",

                color: "#8b5cf6"

            };

        }

        return {

            text: "Hazardous",

            color: "#7c3aed"

        };

    };

    const status = getStatus();

    return (

        <div className="top-pollutant-card">

            <h2>

                🌬 Top Pollutant

            </h2>

            <div className="pollutant-name">

                {pollutant.name}

            </div>

            <div className="pollutant-value">

                {value} μg/m³

            </div>

            <div

                className="pollutant-status"

                style={{

                    background: status.color

                }}

            >

                {status.text}

            </div>

            <div className="pollutant-section">

                <strong>

                    📍 Monitoring Station

                </strong>

                <p>

                    {data.city?.name || "Unavailable"}

                </p>

            </div>

            <div className="pollutant-section">

                <strong>

                    🌍 Primary Source

                </strong>

                <p>

                    {pollutant.reason}

                </p>

            </div>

            <div className="pollutant-section">

                <strong>

                    ❤️ Health Impact

                </strong>

                <p>

                    {pollutant.impact}

                </p>

            </div>

        </div>

    );

}

export default TopPollutant;