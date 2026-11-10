import React, { useEffect, useState } from "react";
import "./WeatherWidget.css";
import { getWeather, getWeatherByLocation } from "../services/backendApi";

function WeatherWidget({
    city,
    lat,
    lon,
    setWeatherCondition
}) {
    const [weather, setWeather] = useState(null);
    const [loading, setLoading] = useState(true);

    const targetKey = city ? city.trim().toLowerCase() : (lat != null && lon != null ? `${Number(lat).toFixed(2)},${Number(lon).toFixed(2)}` : null);

    useEffect(() => {
        if (!targetKey) return;

        let isMounted = true;
        const fetchWeather = async () => {
            try {
                setLoading(true);
                const data = city ? await getWeather(city) : await getWeatherByLocation(lat, lon);
                if (!isMounted) return;
                setWeather(data);
                if (setWeatherCondition) {
                    const cond = data?.weather?.[0]?.main;
                    setWeatherCondition(cond && cond !== "Unavailable" ? cond : "Clear");
                }
            }
            catch (error) {
                console.error("Weather Fetch Error:", error);
                if (isMounted) setWeather(null);
            }
            finally {
                if (isMounted) setLoading(false);
            }
        };

        fetchWeather();

        const interval = setInterval(
            fetchWeather,
            300000
        );

        return () => {
            isMounted = false;
            clearInterval(interval);
        };

    }, [targetKey, city, lat, lon, setWeatherCondition]);



    const formatTime = (timestamp, timeZone) => {
        if (!timestamp) return "--";
        
        const options = {
            hour: "2-digit",
            minute: "2-digit"
        };
        
        if (timeZone) {
            options.timeZone = timeZone;
        }
        
        return new Date(timestamp * 1000).toLocaleTimeString([], options);
    };



    if (loading) {

        return (

            <div className="card weather-card">

                <h2>

                    🌤 Current Weather

                </h2>

                <div className="loading-text">

                    Loading Weather...

                </div>

            </div>

        );

    }



    if (!weather || weather.is_available === false || weather.main?.temp === null) {

        return (

            <div className="card weather-card">

                <h2>

                    🌤 Current Weather

                </h2>

                <div className="loading-text" style={{ padding: "16px", textAlign: "center" }}>

                    <p style={{ margin: "0 0 6px 0", fontWeight: "600" }}>

                        Weather data temporarily unavailable

                    </p>

                    <p style={{ margin: 0, fontSize: "0.85rem", opacity: 0.8 }}>

                        Upstream provider rate limit in cooldown. Retrying automatically.

                    </p>

                </div>

            </div>

        );

    }



    const icon = weather.weather?.[0]?.icon;



    return (

        <div className="card weather-card">

            <div className="weather-header">

                {

                    icon &&

                    <img

                        src={`https://openweathermap.org/img/wn/${icon}@2x.png`}

                        alt="Weather Icon"

                    />

                }

                <div>

                    <h2>

                        🌤 Current Weather

                    </h2>

                    <p className="weather-desc">

                        {

                            weather.weather?.[0]?.description || "N/A"

                        }

                        {

                            weather.source === "STALE_CACHE" &&

                            <span style={{ display: "block", fontSize: "0.75rem", opacity: 0.8, color: "#f59e0b", marginTop: "4px" }}>

                                🕒 Cached data ({weather.cached_at ? new Date(weather.cached_at).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"}) : "earlier"})

                            </span>

                        }

                    </p>

                </div>

            </div>



            <div className="weather-row">

                <span>

                    🌡 Temperature

                </span>

                <span>

                    {weather.main?.temp ?? "--"} °C

                </span>

            </div>



            <div className="weather-row">

                <span>

                    🤗 Feels Like

                </span>

                <span>

                    {weather.main?.feels_like ?? "--"} °C

                </span>

            </div>



            <div className="weather-row">

                <span>

                    💧 Humidity

                </span>

                <span>

                    {weather.main?.humidity ?? "--"} %

                </span>

            </div>



            <div className="weather-row">

                <span>

                    🌬 Wind Speed

                </span>

                <span>
                    {weather.wind?.speed ?? "--"} km/h
                </span>

            </div>



            <div className="weather-row">

                <span>

                    🧭 Wind Direction

                </span>

                <span>

                    {weather.wind?.deg ?? "--"}°

                </span>

            </div>



            <div className="weather-row">

                <span>

                    ☁ Condition

                </span>

                <span>

                    {weather.weather?.[0]?.main ?? "--"}

                </span>

            </div>



            <div className="weather-row">

                <span>

                    🌅 Sunrise

                </span>

                <span>
                    {formatTime(weather.sys?.sunrise, weather.timezone)}
                </span>

            </div>



            <div className="weather-row">

                <span>

                    🌇 Sunset

                </span>

                <span>
                    {formatTime(weather.sys?.sunset, weather.timezone)}
                </span>

            </div>



            <div className="weather-row">

                <span>

                    📍 City

                </span>

                <span>

                    {weather.name || "--"}

                </span>

            </div>



            <div className="weather-row">

                <span>

                    🌍 Country

                </span>

                <span>

                    {weather.sys?.country || "--"}

                </span>

            </div>

        </div>

    );

}

export default WeatherWidget;