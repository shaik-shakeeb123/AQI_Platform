import React from "react";
import "./AQIDetails.css";

function AQIDetails({ data }) {

    if (!data) {

        return (

            <div className="card aqi-details-card">

                <h2>

                    🌡 AQI Details

                </h2>

                <div className="loading-text">

                    Loading Details...

                </div>

            </div>

        );

    }

    const details = [

        {
            label: "🌡 Temperature",
            value: `${data.iaqi?.t?.v ?? "N/A"} °C`
        },

        {
            label: "💧 Humidity",
            value: `${data.iaqi?.h?.v ?? "N/A"} %`
        },

        {
            label: "🌬 Wind Speed",
            value: `${data.iaqi?.w?.v ?? "N/A"} km/h`
        },

        {
            label: "🧭 Wind Direction",
            value: `${data.iaqi?.wd?.v ?? "N/A"}°`
        },

        {
            label: "🌤 Pressure",
            value: `${data.iaqi?.p?.v ?? "N/A"} hPa`
        },

        {
            label: "🌫 PM2.5",
            value: data.iaqi?.pm25?.v ?? "N/A"
        },

        {
            label: "🌫 PM10",
            value: data.iaqi?.pm10?.v ?? "N/A"
        },

        {
            label: "🟤 NO₂",
            value: data.iaqi?.no2?.v ?? "N/A"
        },

        {
            label: "🟢 O₃",
            value: data.iaqi?.o3?.v ?? "N/A"
        },

        {
            label: "⚫ CO",
            value: data.iaqi?.co?.v ?? "N/A"
        },

        {
            label: "🟡 SO₂",
            value: data.iaqi?.so2?.v ?? "N/A"
        }

    ];

    return (

        <div className="card aqi-details-card">

            <h2>

                🌡 AQI Details

            </h2>

            {

                details.map((item, index) => (

                    <div

                        key={index}

                        className="detail-row"

                    >

                        <span>

                            {item.label}

                        </span>

                        <span>

                            {item.value}

                        </span>

                    </div>

                ))

            }

        </div>

    );

}

export default AQIDetails;