import React from "react";
import { Line } from "react-chartjs-2";
import "./AQIChart.css";

import {
    Chart as ChartJS,
    LineElement,
    CategoryScale,
    LinearScale,
    PointElement,
    Tooltip,
    Legend,
    Filler
} from "chart.js";

ChartJS.register(
    LineElement,
    CategoryScale,
    LinearScale,
    PointElement,
    Tooltip,
    Legend,
    Filler
);

// Plugin to draw AQI colored background bands
const aqiBackgroundPlugin = {

    id: "aqiBackground",

    beforeDraw(chart) {

        const {

            ctx,

            chartArea,

            scales

        } = chart;

        if (!chartArea) return;

        const { left, right } = chartArea;
        const y = scales.y;

        

        const ranges = [

            { min: 0, max: 50, color: "rgba(34,197,94,0.12)" },
            { min: 50, max: 100, color: "rgba(234,179,8,0.12)" },
            { min: 100, max: 150, color: "rgba(249,115,22,0.12)" },
            { min: 150, max: 200, color: "rgba(239,68,68,0.12)" },
            { min: 200, max: 300, color: "rgba(147,51,234,0.12)" },
            { min: 300, max: 500, color: "rgba(127,29,29,0.12)" }

        ];

        ctx.save();

        ranges.forEach(range => {

            const top = y.getPixelForValue(range.max);
            const bottom = y.getPixelForValue(range.min);

            ctx.fillStyle = range.color;

            ctx.fillRect(

                left,

                top,

                right - left,

                bottom - top

            );

        });

        ctx.restore();

    }

};

ChartJS.register(aqiBackgroundPlugin);

function AQIChart({ data }) {

    const safeData = Array.isArray(data) ? data : [];

    const getColor = (value) => {

        if (value <= 50) return "#22c55e";

        if (value <= 100) return "#eab308";

        if (value <= 150) return "#f97316";

        if (value <= 200) return "#ef4444";

        if (value <= 300) return "#9333ea";

        return "#7f1d1d";

    };

    const chartData = {

        labels: [

            "1 Hour",

            "3 Hours",

            "6 Hours",

            "12 Hours",

            "24 Hours"

        ],

        datasets: [

            {

                label: "Predicted AQI",

                data: safeData,

                fill: true,

                borderWidth: 4,

                tension: 0.45,

                backgroundColor: "rgba(37,99,235,0.08)",

                pointRadius: 7,

                pointHoverRadius: 10,

                pointBackgroundColor:

                    safeData.map(value => getColor(value)),

                pointBorderColor:

                    safeData.map(value => getColor(value)),

                pointBorderWidth: 3,

                segment: {

                    borderColor: ctx => {

                        const value = ctx.p1.parsed.y;

                        return getColor(value);

                    }

                }

            }

        ]

    };

    const options = {

        responsive: true,

        maintainAspectRatio: false,

        animation: {

            duration: 1200

        },

        interaction: {

            mode: "nearest",

            intersect: false

        },

        plugins: {

            legend: {

                display: true,

                position: "top"

            },

            tooltip: {

                callbacks: {

                    label: (context) =>

                        ` AQI : ${context.parsed.y}`

                }

            }

        },

        scales: {

            y: {

                min: 0,

                max: 350,

                ticks: {

                    stepSize: 50

                },

                title: {

                    display: true,

                    text: "AQI"

                },

                grid: {

                    color: "rgba(148,163,184,.18)"

                }

            },

            x: {

                title: {

                    display: true,

                    text: "Prediction Time"

                },

                grid: {

                    display: false

                }

            }

        }

    };

    return (

        <div className="card chart-card">

            <h2>

                📈 AQI Prediction

            </h2>

            {

                safeData.length === 5 ?

                (

                    <div className="chart-container">

                        <Line

                            data={chartData}

                            options={options}

                        />

                    </div>

                )

                :

                (

                    <div className="loading-text">

                        Loading Prediction...

                    </div>

                )

            }

            <div className="aqi-legend">

                <span style={{color:"#22c55e"}}>● Good</span>

                <span style={{color:"#eab308"}}>● Moderate</span>

                <span style={{color:"#f97316"}}>● USG</span>

                <span style={{color:"#ef4444"}}>● Unhealthy</span>

                <span style={{color:"#9333ea"}}>● Very Unhealthy</span>

                <span style={{color:"#7f1d1d"}}>● Hazardous</span>

            </div>

        </div>

    );

}

export default AQIChart;