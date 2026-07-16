import React from "react";
import "./AISummary.css";

function AISummary({

    aqi,

    data,

    prediction,

    updatedAt,

    weatherCondition

}) {

    if (!data) {

        return null;

    }

    const pollutant =

        data?.dominentpol?.toUpperCase()

        ||

        "Unknown";



    // AQI Status

    let status = "";

    let outdoor = "";

    let color = "";



    if (aqi <= 50) {

        status = "Good";

        outdoor =

            "Outdoor activities are completely safe.";

        color = "#22c55e";

    }

    else if (aqi <= 100) {

        status = "Moderate";

        outdoor =

            "Most people can enjoy outdoor activities. Sensitive individuals should take precautions.";

        color = "#eab308";

    }

    else if (aqi <= 150) {

        status =

            "Unhealthy for Sensitive Groups";

        outdoor =

            "Sensitive groups should reduce outdoor exposure.";

        color = "#f97316";

    }

    else if (aqi <= 200) {

        status = "Unhealthy";

        outdoor =

            "Reduce outdoor activities whenever possible.";

        color = "#ef4444";

    }

    else {

        status = "Hazardous";

        outdoor =

            "Avoid outdoor exposure.";

        color = "#7f1d1d";

    }



    // Prediction Insight

    let predictionText =

        "Prediction unavailable.";



    if (

        Array.isArray(prediction)

        &&

        prediction.length >= 2

    ) {

        const first = prediction[0];

        const last =

            prediction[prediction.length - 1];



        if (last > first + 5) {

            predictionText =

                "Air quality is expected to worsen over the next few hours.";

        }

        else if (last < first - 5) {

            predictionText =

                "Air quality is expected to improve over the next few hours.";

        }

        else {

            predictionText =

                "Air quality is expected to remain relatively stable.";

        }

    }



    return (

        <div className="ai-summary-card">

            <div className="ai-header">

                🤖 AI Air Quality Summary

            </div>



            <div

                className="ai-status"

                style={{

                    background: color

                }}

            >

                AQI {aqi} • {status}

            </div>



            <div className="ai-content">

                <p>

                    <strong>🌫 Dominant Pollutant:</strong>

                    {" "}

                    {pollutant}

                </p>



                <p>

                    <strong>🌤 Weather:</strong>

                    {" "}

                    {weatherCondition || "Unknown"}

                </p>



                <p>

                    <strong>🚶 Outdoor Advice:</strong>

                    {" "}

                    {outdoor}

                </p>



                <p>

                    <strong>📈 AI Prediction:</strong>

                    {" "}

                    {predictionText}

                </p>



                <p>

                    <strong>🕒 Updated:</strong>

                    {" "}

                    {updatedAt}

                </p>

            </div>



            <div className="ai-footer">

                💡 This summary is generated automatically from live AQI, weather and prediction data.

            </div>

        </div>

    );

}

export default AISummary;