import React, { useState, useEffect, Suspense, lazy, useCallback } from "react";
import "./App.css";

import { useAuth } from "./context/AuthContext";

import WeatherBackground from "./components/WeatherBackground";
import Sidebar from "./components/Sidebar";
import ThemeToggle from "./components/ThemeToggle";
import SearchBar from "./components/SearchBar";
import FavoriteCities from "./components/FavoriteCities";
import ToastNotification from "./components/ToastNotification";
import AQICard from "./components/AQICard";
import AQIGauge from "./components/AQIGauge";
import AQIDetails from "./components/AQIDetails";
import AQIChart from "./components/AQIChart";
import { cities } from "./data/indianCities";
import WeatherWidget from "./components/WeatherWidget";
import CityInfo from "./components/CityInfo";
import SafeOutdoorWindow from "./components/SafeOutdoorWindow";
import HealthInsights from "./components/HealthInsights";
import PollutionTips from "./components/PollutionTips";
import TopPollutant from "./components/TopPollutant";
import AISummary from "./components/AISummary";
import CountdownTimer from "./components/CountdownTimer";
import PageWrapper from "./components/PageWrapper";
import { getCurrentAQI, getCurrentAQIByLocation, fetchPredictionData, getExposureAnalytics, getHealthInsights, getSafeWindow } from "./services/backendApi";

// Lazy Loaded Components
const AQIHeatmap = lazy(() => import("./components/AQIHeatmap"));
const NotificationPanel = lazy(() => import("./components/NotificationPanel"));
const AlertPanel = lazy(() => import("./components/AlertPanel"));
const MapView = lazy(() => import("./components/MapView"));
const Profile = lazy(() => import("./components/Profile"));
const Settings = lazy(() => import("./components/Settings"));
const Auth = lazy(() => import("./components/Auth"));
const CompleteProfile = lazy(() => import("./components/CompleteProfile"));

function App() {

const { user, logout } = useAuth();

const [page,setPage]=useState("dashboard");

const [city,setCity]=useState("Delhi");

const [aqi,setAqi]=useState(null);

const [aqiData,setAqiData]=useState(null);

const [prediction,setPrediction]=useState([]);

const [weather,setWeather]=useState("");

const [theme,setTheme]=useState("dark");

const [loading,setLoading]=useState(false);

const [updatedAt,setUpdatedAt]=useState("");

const [safeTime,setSafeTime]=useState("");

const [notifications,setNotifications]=useState([]);

const [showAuth,setShowAuth]=useState(false);
const [toast, setToast] = useState(null);

const [lat,setLat]=useState(null);

const [lon,setLon]=useState(null);
const [usingNearestCity, setUsingNearestCity] = useState(false);
const [exposureData, setExposureData] = useState(null);
const [exposureLoading, setExposureLoading] = useState(false);
const [exposureError, setExposureError] = useState(null);

const [healthInsights, setHealthInsights] = useState(null);
const [safeWindow, setSafeWindow] = useState(null);
const [loadingHealth, setLoadingHealth] = useState(false);
const [loadingSafeWindow, setLoadingSafeWindow] = useState(false);
const [healthError, setHealthError] = useState(null);
const [safeWindowError, setSafeWindowError] = useState(null);
const favorites=[
"Delhi",
"Mumbai",
"Hyderabad",
"Chennai",
"Kolkata",
"Bengaluru",
"Patna",
"Lucknow",
"Jaipur"
];
//const [toast, setToast] = useState(null);
useEffect(() => {
    if (user) {
        setShowAuth(false);
    } else {
        setShowAuth(true);
    }
}, [user]);
// ======================================
// Notification Manager
// ======================================

const addNotification = (aqi) => {

    let notification = {};

    if (aqi <= 50) {

        notification = {
            title: "🌿 Good Air Quality",
            message: "Air quality is good and safe."
        };

    }

    else if (aqi <= 100) {

        notification = {
            title: "🙂 Moderate AQI",
            message: "Air quality is acceptable for most people."
        };

    }

    else if (aqi <= 150) {

        notification = {
            title: "😷 AQI Warning",
            message: "Sensitive groups should limit outdoor activities."
        };

    }

    else if (aqi <= 200) {

        notification = {
            title: "⚠ Unhealthy Air",
            message: "Reduce prolonged outdoor exposure."
        };

    }

    else {

        notification = {
            title: "☠ Hazardous Air",
            message: "Stay indoors whenever possible."
        };

    }

    setNotifications((prev) => [

        notification,

        ...prev

    ].slice(0, 10));

};



// ======================================
// AQI Theme
// ======================================

const getAQITheme = () => {

    if (aqi === null)
        return "";

    if (aqi <= 50)
        return "good";

    if (aqi <= 100)
        return "moderate";

    if (aqi <= 150)
        return "usg";

    if (aqi <= 200)
        return "unhealthy";

    return "hazardous";

};



// ======================================
// Safe Outdoor Recommendation
// ======================================

const updateSafeTime = (value) => {

    if (value <= 50) {

        setSafeTime(
            "Excellent air quality 🌿"
        );

    }

    else if (value <= 100) {

        setSafeTime(
            "Safe for most people."
        );

    }

    else if (value <= 150) {

        setSafeTime(
            "Sensitive groups should be careful."
        );

    }

    else if (value <= 200) {

        setSafeTime(
            "Avoid outdoor exercise."
        );

    }

    else {

        setSafeTime(
            "Stay indoors as much as possible."
        );

    }

};



// ======================================
// Flask ML Prediction
// ======================================

const fetchPrediction = useCallback(async (cityName, aqiData, currentAqiValue) => {
    try {
        const result = await fetchPredictionData(cityName, aqiData, currentAqiValue);
        if (result.success) {
            const values = [
                result.predictions["1h"],
                result.predictions["3h"],
                result.predictions["6h"],
                result.predictions["12h"],
                result.predictions["24h"]
            ];
            setPrediction(values);
            console.log("Prediction:", values);
        }
    } catch (err) {
        console.log("Prediction API Error");
        console.log(err);
    }
}, []);

// ======================================
// Common AQI Data Handler
// ======================================

const processAQIData = useCallback(async (data, cityName = null) => {

    if (data.status !== "ok") {
        console.error("WAQI Status:", data.status);
        console.error("WAQI Error Data:", data.data);
        console.error("Full Response:", data);

        setNotifications((prev) => [
            {
                title: "⚠ AQI Service Unavailable",
                message: "Unable to fetch live AQI data."
            },
            ...prev
        ].slice(0,10));

        return;
    }

    const value = data.data.aqi;

    setAqi(value);
    setAqiData(data.data);
    addNotification(value);
    updateSafeTime(value);
    setUpdatedAt(new Date().toLocaleTimeString());
    const resolvedCity = cityName || data.data.city.name;
    setCity(resolvedCity);

    if (data.data.city?.geo) {
        setLat(data.data.city.geo[0]);
        setLon(data.data.city.geo[1]);
    }

    await fetchPrediction(resolvedCity, data.data, value);

}, [fetchPrediction]);



// ======================================
// Search by City
// ======================================

const fetchHealthAndSafeWindow = useCallback(async (targetCity) => {
    if (!targetCity) return;
    setLoadingHealth(true);
    setHealthError(null);
    setLoadingSafeWindow(true);
    setSafeWindowError(null);
    try {
        const [hData, sData] = await Promise.all([
            getHealthInsights(targetCity).catch(err => {
                console.error("Failed to fetch health insights:", err);
                setHealthError(err.message || "Failed to load health insights");
                return null;
            }),
            getSafeWindow({ city: targetCity }).catch(err => {
                console.error("Failed to fetch safe outdoor window:", err);
                setSafeWindowError(err.message || "Failed to load safe outdoor window");
                return null;
            })
        ]);
        setHealthInsights(hData);
        setSafeWindow(sData);
    } catch (err) {
        console.error("Error in fetchHealthAndSafeWindow:", err);
    } finally {
        setLoadingHealth(false);
        setLoadingSafeWindow(false);
    }
}, []);

const fetchAQI = useCallback(async (targetCity) => {
    if (!targetCity) return;
    try {
        setLoading(true);
        setExposureLoading(true);
        setExposureError(null);

        const [data, expData] = await Promise.all([
            getCurrentAQI(targetCity),
            getExposureAnalytics(targetCity).catch(err => {
                console.error("Failed to fetch exposure insights inside fetchAQI:", err);
                setExposureError(err.message || "Failed to load exposure data");
                return null;
            })
        ]);

        setExposureData(expData);
        await processAQIData(data, targetCity);
        await fetchHealthAndSafeWindow(targetCity);
    } catch(err) {
        console.log(err);
    } finally {
        setLoading(false);
        setExposureLoading(false);
    }
}, [processAQIData, fetchHealthAndSafeWindow]);

const fetchNearestCityAQI = useCallback(async (latitude, longitude) => {
    try {
        let nearestCity = null;
        let minimumDistance = Number.MAX_VALUE;

        cities.forEach((cityObj) => {
            const distance = Math.sqrt(
                Math.pow(latitude - cityObj.lat, 2) +
                Math.pow(longitude - cityObj.lon, 2)
            );
            if (distance < minimumDistance) {
                minimumDistance = distance;
                nearestCity = cityObj;
            }
        });

        if (!nearestCity) {
            console.log("No nearest city found. Falling back to Delhi.");
            setUsingNearestCity(true);
            await fetchAQI("Delhi");
            return;
        }

        console.log("Nearest City:", nearestCity.name);
        setUsingNearestCity(true);

        setNotifications((prev) => [
            {
                title: "📍 Current Location Unavailable",
                message: `Live AQI is unavailable for your exact GPS location. Displaying data from the nearest monitoring station (${nearestCity.name}).`
            },
            ...prev
        ].slice(0, 10));

        await fetchAQI(nearestCity.name);

    } catch (err) {
        console.error("Nearest City Error:", err);
        setUsingNearestCity(true);

        setNotifications((prev) => [
            {
                title: "⚠ Unable to Find Nearby Station",
                message: "Showing AQI for Delhi as a fallback."
            },
            ...prev
        ].slice(0, 10));

        await fetchAQI("Delhi");
    }
}, [fetchAQI]);

const fetchAQIByLocation = useCallback(async (latitude, longitude) => {
    try {
        setLoading(true);
        setExposureLoading(true);
        setExposureError(null);

        const data = await getCurrentAQIByLocation(latitude, longitude);
        setUsingNearestCity(false);

        const resolvedCity = data.data?.city?.name || "Delhi";
        try {
            const expData = await getExposureAnalytics(resolvedCity);
            setExposureData(expData);
        } catch (err) {
            console.error("Failed to fetch exposure insights in location mode:", err);
            setExposureError(err.message || "Failed to load exposure data");
            setExposureData(null);
        }

        await processAQIData(data, resolvedCity);
        await fetchHealthAndSafeWindow(resolvedCity);
    } catch (err) {
        console.error(err);
        await fetchNearestCityAQI(latitude, longitude);
    } finally {
        setLoading(false);
        setExposureLoading(false);
    }
}, [processAQIData, fetchHealthAndSafeWindow, fetchNearestCityAQI]);
const showToast = (

    type,

    title,

    message,

    icon = null

) => {

    setToast({

        type,

        title,

        message,

        icon

    });

};

// ======================================
// Get User Location on App Start
// ======================================

useEffect(() => {

    if (!navigator.geolocation) {

        fetchAQI("Delhi");

        return;

    }

    navigator.geolocation.getCurrentPosition(

        (position) => {

            const latitude = position.coords.latitude;
            const longitude = position.coords.longitude;

            setLat(latitude);
            setLon(longitude);

            fetchAQIByLocation(

                latitude,

                longitude

            );

        },

        () => {

            fetchAQI("Delhi");

        }

    );
    showToast(

    "success",

    "Welcome",

    "AQI Insight Pro Loaded Successfully",

    "🌍"

);

}, [fetchAQI, fetchAQIByLocation]);

// ======================================
// Load Saved Theme
// ======================================

useEffect(() => {

    const savedTheme = localStorage.getItem("theme");

    if (savedTheme) {

        setTheme(savedTheme);

    }

}, []);


// ======================================
// Save Theme
// ======================================

useEffect(() => {

    localStorage.setItem(

        "theme",

        theme

    );

}, [theme]);
// ======================================
// Refresh AQI Every 3 Minutes
// ======================================

useEffect(() => {

    const interval = setInterval(() => {

        if (

            lat !== null &&

            lon !== null

        ) {

            fetchAQIByLocation(

                lat,

                lon

            );

        }

        else {

            fetchAQI(city);

        }

    }, 180000);

    return () => clearInterval(interval);

}, [

    lat,

    lon,

    city,
    fetchAQI,
    fetchAQIByLocation
]);

useEffect(() => {

    console.log("AQI:", aqi);

    console.log("City:", city);

    console.log("Prediction:", prediction);

}, [

    aqi,

    city,

    prediction

]);

    const { needsOnboarding } = useAuth();

    if (user && needsOnboarding) {
        return (
            <div className={`main-container ${theme} ${getAQITheme()}`}>
                <WeatherBackground weather={weather}/>
                <Suspense fallback={<div className="loading-spinner" style={{margin: 'auto'}}>Loading Setup...</div>}>
                    <CompleteProfile />
                </Suspense>
            </div>
        );
    }

    return(

<div className={`main-container ${theme} ${getAQITheme()}`}>

<WeatherBackground weather={weather}/>

<Sidebar

page={page}

setPage={setPage}

/>

<div className="app">
<header className="hero-header">

    <div className="hero-left">

        <div>

            <h1 className="hero-title">

                AQI <span>Insight Pro</span>

            </h1>

            <p className="hero-subtitle">

                🌍 Real-Time Air Quality Intelligence Platform

            </p>

        </div>

    </div>

    <div className="hero-right">

        <div className="status-card">

            <div className="live-badge">

                🟢 LIVE

            </div>

            <div>

                <small>Updated</small>

                <h4>{updatedAt || "--:--:--"}</h4>

            </div>

            <CountdownTimer initialSeconds={180} />
        </div>

        <ThemeToggle

            theme={theme}

            setTheme={setTheme}

        />

        {

            user ?

            (

                <button

                    className="login-btn"

                    onClick={() => logout()}

                >

                    Logout

                </button>

            )

            :

            (

                <button

                    className="login-btn"

                    onClick={() => setShowAuth(true)}

                >

                    Login / Register

                </button>

            )

        }

    </div>

</header>





<div className="search-section">

    <div className="search-box">

        <SearchBar

            onSearch={fetchAQI}

        />

    </div>



    <button

        className="current-location-btn"

        onClick={() => {

            if (!navigator.geolocation) {

                alert(

                    "Geolocation is not supported."

                );

                return;

            }

            setLoading(true);

            navigator.geolocation.getCurrentPosition(

                (position) => {

                    const latitude =

                        position.coords.latitude;

                    const longitude =

                        position.coords.longitude;

                    setLat(latitude);

                    setLon(longitude);

                    fetchAQIByLocation(

                        latitude,

                        longitude

                    );

                },

                (error) => {

                    setLoading(false);

                    switch (error.code) {

                        case error.PERMISSION_DENIED:

                            alert(

                                "Location permission denied."

                            );

                            break;

                        case error.POSITION_UNAVAILABLE:

                            alert(

                                "Location unavailable."

                            );

                            break;

                        case error.TIMEOUT:

                            alert(

                                "Location request timed out."

                            );

                            break;

                        default:

                            alert(

                                "Unable to fetch location."

                            );

                    }

                },

                {

                    enableHighAccuracy: true,

                    timeout: 10000,

                    maximumAge: 0

                }

            );

        }}

    >

        {

            loading ?

            "📡 Detecting Location..."

            :

            "📍 Use My Current Location"

        }

    </button>

</div>


<div className="favorite-section">
    <FavoriteCities

        favorites={favorites}

        onSelect={fetchAQI}

        selectedCity={city}

    />

</div>


<div className="section">

<div className="feature-row">

<div className="feature-card">

🌿

<h4>

Real-time AQI

</h4>

<p>

Live Updates

</p>

</div>


<div className="feature-card">

🛡

<h4>

Trusted Data

</h4>

<p>

Accurate & Reliable

</p>

</div>



<div className="feature-card">

🔔

<h4>

Smart Alerts

</h4>

<p>

Stay Informed

</p>

</div>



<div className="feature-card">

🩺

<h4>

Health Insights

</h4>

<p>

Breathe Better

</p>

</div>

</div>
</div>

{

page==="dashboard"

&&

(

loading

?

(

<div className="loader">

<div className="loader-page">

<div className="loader-circle"/>

<h2>

Loading Live AQI Data...

</h2>

<p>

Fetching latest environmental information

</p>

</div>

</div>

)

:

(

aqi!==null &&

<PageWrapper>
<div className="dashboard">
    <h2 className="dashboard-title">

    🌍 Air Quality Overview

</h2>
    <div className="hero-dashboard">

        <div className="hero-left-card">

            <AQICard
                aqi={aqi}
                data={aqiData}
                updatedAt={updatedAt}
            />
            <WeatherWidget
                city={city}
                lat={lat}
                lon={lon}
                setWeatherCondition={setWeather}
            />

        </div>

        <div className="hero-right-grid">
            <AISummary
            aqi={aqi}
            data={aqiData}
            prediction={prediction}
            updatedAt={updatedAt}
            weatherCondition={weather}
            />         
        
            <AQIGauge
                aqi={aqi}
                exposureData={exposureData}
                loading={exposureLoading}
                error={exposureError}
            />

        </div>

    </div>

    <h2 className="dashboard-title">

        📍 Environmental Details

    </h2>


    <div className="info-grid">

        <CityInfo
            data={aqiData}
            updatedAt={updatedAt}
            lat={lat}
            lon={lon}
            usingNearestCity={usingNearestCity}
        />

        <AQIDetails
            data={aqiData}
        />

    </div>


    <h2 className="dashboard-title">

    🩺 Health Analytics

    </h2>
    

    <div className="health-grid">

        <TopPollutant
            data={aqiData}
        />

        <HealthInsights
            aqi={aqi}
            healthInsights={healthInsights}
            loading={loadingHealth}
            error={healthError}
        />

    </div>

    <h2 className="dashboard-title">

    💡 Personalized Recommendations

    </h2>

    <div className="recommendation-grid">

        {

            user ?

            (

                <SafeOutdoorWindow
                    aqi={aqi}
                    safeWindow={safeWindow}
                    loading={loadingSafeWindow}
                    error={safeWindowError}
                />

            )

            :

            (

                <div className="card">

                    <h2>

                        🌤 Personalized Outdoor Recommendation

                    </h2>

                    <p>

                        Login to receive personalized recommendations based on your health profile.

                    </p>

                    <button

                        className="login-btn"

                        onClick={() => setShowAuth(true)}

                    >

                        Login

                    </button>

                </div>

            )

        }

        <PollutionTips
            aqi={aqi}
        />

    </div>

    <h2 className="dashboard-title">

    📈 AQI Prediction & Forecast

    </h2>

   

    <div className="full-width-card">

        <AQIChart
            data={prediction}
        />

    </div>

</div>
</PageWrapper>
)

)

}
{

page==="alerts"

&&
<PageWrapper>


<AlertPanel

aqi={aqi}

/>

</PageWrapper>

}
{

page==="heatmap"

&&
<PageWrapper>

<AQIHeatmap

lat={lat}

lon={lon}

aqi={aqi}

/>
</PageWrapper>
}
{

page==="route"

&&
<PageWrapper>

<MapView

lat={lat}

lon={lon}

aqi={aqi}

/>
</PageWrapper>

}
{

page==="profile"

&&

<PageWrapper>

{

user ? (

<Profile/>

) : (

<div className="card">

<h2>

🔒 Login Required

</h2>

<p>

Please login to view your profile.

</p>

<button

className="login-btn"

onClick={()=>setShowAuth(true)}

>

Login

</button>

</div>

)

}

</PageWrapper>

}
{

page==="settings"

&&
<PageWrapper>

<Settings

theme={theme}

setTheme={setTheme}

/>
</PageWrapper>
}
{

page==="notifications"

&&
<PageWrapper>

<NotificationPanel

notifications={notifications}

aqi={aqi}

safeTime={safeTime}

city={city}

updatedAt={updatedAt}

/>
</PageWrapper>
}
{

showAuth

&&

<div className="auth-overlay">

<div className="auth-modal">

<button

className="close-btn"

onClick={()=>setShowAuth(false)}

>

✕

</button>

<Auth/>

<ToastNotification
    notification={toast}
    onClose={() => setToast(null)}
/>

</div>

</div>

}
</div>
</div>

);

}

export default App;