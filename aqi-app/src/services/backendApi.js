import { adaptCurrentAQI } from "./aqiAdapter";
import { adaptPrediction } from "./predictionAdapter";
import { adaptWeather } from "./weatherAdapter";

const BASE_URL = process.env.REACT_APP_API_URL || "";

const getHeaders = (headers = {}) => {
    const token = localStorage.getItem("token");
    const result = { ...headers };
    if (token) {
        result["Authorization"] = `Bearer ${token}`;
    }
    return result;
};

export const getCurrentAQI = async (city) => {
    const response = await fetch(`${BASE_URL}/currentAQI?city=${encodeURIComponent(city)}`, {
        headers: getHeaders()
    });
    if (!response.ok) {
        throw new Error(`Failed to fetch current AQI: ${response.statusText}`);
    }
    const data = await response.json();
    return adaptCurrentAQI(data);
};

export const getCurrentAQIByLocation = async (lat, lon) => {
    const geoResponse = await fetch(
        `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lon}`
    );
    if (!geoResponse.ok) {
        throw new Error("Location geocoding failed");
    }
    const geoData = await geoResponse.json();
    const city = geoData.address.city || 
                 geoData.address.town || 
                 geoData.address.village || 
                 geoData.address.suburb || 
                 "Delhi";
                 
    return getCurrentAQI(city);
};

export const fetchPredictionData = async (city, aqiData, currentAqi) => {
    const horizons = ["1h", "3h", "6h", "12h", "24h"];
    
    const pm25 = aqiData.iaqi?.pm25?.v ?? null;
    const pm10 = aqiData.iaqi?.pm10?.v ?? null;
    const co = aqiData.iaqi?.co?.v ?? null;
    const no2 = aqiData.iaqi?.no2?.v ?? null;
    const so2 = aqiData.iaqi?.so2?.v ?? null;
    const o3 = aqiData.iaqi?.o3?.v ?? null;
    const temperature = aqiData.iaqi?.t?.v ?? null;
    const humidity = aqiData.iaqi?.h?.v ?? null;

    const promises = horizons.map(h =>
        fetch(`${BASE_URL}/predictAQI`, {
            method: "POST",
            headers: getHeaders({
                "Content-Type": "application/json"
            }),
            body: JSON.stringify({
                city: city,
                horizon: h,
                pm25,
                pm10,
                co,
                no2,
                so2,
                o3,
                temperature,
                humidity
            })
        })
        .then(async (res) => {
            if (!res.ok) {
                return { horizon: h, predicted_aqi: null };
            }
            const data = await res.json();
            return { ...data, horizon: h };
        })
        .catch(() => ({ horizon: h, predicted_aqi: null }))
    );

    const responses = await Promise.all(promises);
    return adaptPrediction(responses, currentAqi);
};

export const getWeather = async (city) => {
    const response = await fetch(`${BASE_URL}/weather?city=${encodeURIComponent(city)}`, {
        headers: getHeaders()
    });
    if (!response.ok) {
        throw new Error(`Failed to fetch weather: ${response.statusText}`);
    }
    const data = await response.json();
    return adaptWeather(data);
};

export const getWeatherByLocation = async (lat, lon) => {
    const geoResponse = await fetch(
        `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lon}`
    );
    if (!geoResponse.ok) {
        throw new Error("Location geocoding failed");
    }
    const geoData = await geoResponse.json();
    const city = geoData.address.city || 
                 geoData.address.town || 
                 geoData.address.village || 
                 geoData.address.suburb || 
                 "Delhi";
                 
    return getWeather(city);
};

export const getExposureAnalytics = async (city) => {
    const response = await fetch(`${BASE_URL}/exposure?city=${encodeURIComponent(city)}`, {
        headers: getHeaders()
    });
    if (!response.ok) {
        throw new Error(`Failed to fetch exposure analytics: ${response.statusText}`);
    }
    return await response.json();
};

export const getRoute = async (source, destination, city = null) => {
    const body = {
        start_point: source,
        destination: destination
    };
    if (city) {
        body.city = city;
    }

    const response = await fetch(`${BASE_URL}/getRoute`, {
        method: "POST",
        headers: getHeaders({
            "Content-Type": "application/json"
        }),
        body: JSON.stringify(body)
    });

    if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Failed to optimize route: ${response.statusText}`);
    }

    return await response.json();
};

export const getHealthInsights = async (city, options = {}) => {
    const { signal, timeout = 8000 } = options;
    const controller = new AbortController();
    const id = setTimeout(() => controller.abort(), timeout);
    
    try {
        const response = await fetch(`${BASE_URL}/getHealthInsights?city=${encodeURIComponent(city)}`, {
            signal: signal || controller.signal,
            headers: getHeaders()
        });
        clearTimeout(id);
        if (!response.ok) {
            throw new Error(`Failed to fetch health insights: ${response.statusText}`);
        }
        return await response.json();
    } catch (err) {
        clearTimeout(id);
        throw err;
    }
};

export const getSafeWindow = async (payload, options = {}) => {
    const { signal, timeout = 8000 } = options;
    const controller = new AbortController();
    const id = setTimeout(() => controller.abort(), timeout);
    
    try {
        const response = await fetch(`${BASE_URL}/getSafeWindow`, {
            method: "POST",
            headers: getHeaders({
                "Content-Type": "application/json"
            }),
            body: JSON.stringify(payload),
            signal: signal || controller.signal
        });
        clearTimeout(id);
        if (!response.ok) {
            throw new Error(`Failed to calculate safe outdoor window: ${response.statusText}`);
        }
        return await response.json();
    } catch (err) {
        clearTimeout(id);
        throw err;
    }
};
