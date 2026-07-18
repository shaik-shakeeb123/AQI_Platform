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

    useEffect(() => {
        if (!city && (lat == null || lon == null)) return;

        const fetchWeather = async () => {
            try {
                setLoading(true);
                const data = city ? await getWeather(city) : await getWeatherByLocation(lat, lon);
                setWeather(data);
                if (setWeatherCondition && data) {
                    setWeatherCondition(
                        data.weather?.[0]?.main || "Clear"
                    );
                }
            }
            catch (error) {
                console.error("Weather Fetch Error:", error);
                setWeather(null);
            }
            finally {
                setLoading(false);
            }
        };

        fetchWeather();

        const interval = setInterval(
            fetchWeather,
            180000
        );

        return () => clearInterval(interval);

    }, [
        city,
        lat,
        lon,
        setWeatherCondition
    ]);



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



    if (!weather) {

        return (

            <div className="card weather-card">

                <h2>

                    🌤 Current Weather

                </h2>

                <div className="loading-text">

                    Weather data unavailable

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