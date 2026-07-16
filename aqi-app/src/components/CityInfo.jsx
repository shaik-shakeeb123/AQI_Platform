import React from "react";
import "./CityInfo.css";

function CityInfo({

    data,

    updatedAt,

    lat,

    lon

}) {

    if (!data) {

        return (

            <div className="card city-card">

                <h2>

                    📍 Current Location

                </h2>

                <div className="loading-text">

                    Loading Location...

                </div>

            </div>

        );

    }

    const stationName = data.city?.name || "Unknown";

    const country =

        stationName.includes(",")

            ? stationName.split(",").pop().trim()

            : "N/A";

    return (

        <div className="card city-card">

            <h2>

                📍 Current Location

            </h2>

            <div className="city-row">

                <span>

                    🏙 Station

                </span>

                <span title={stationName}>

                    {stationName}

                </span>

            </div>

            <div className="city-row">

                <span>

                    🌍 Country

                </span>

                <span>

                    {country}

                </span>

            </div>

            <div className="city-row">

                <span>

                    🌫 AQI

                </span>

                <span>

                    {data.aqi ?? "--"}

                </span>

            </div>

            <div className="city-row">

                <span>

                    🕒 Updated

                </span>

                <span>

                    {updatedAt || "--"}

                </span>

            </div>

            <div className="city-row">

                <span>

                    📌 Latitude

                </span>

                <span>

                    {lat != null ? lat.toFixed(4) : "--"}

                </span>

            </div>

            <div className="city-row">

                <span>

                    📌 Longitude

                </span>

                <span>

                    {lon != null ? lon.toFixed(4) : "--"}

                </span>

            </div>

        </div>

    );

}

export default CityInfo;