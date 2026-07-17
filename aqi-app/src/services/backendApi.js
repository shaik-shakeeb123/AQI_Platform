import apiClient from "./apiClient";
import axios from "axios";
import { adaptCurrentAQI } from "./aqiAdapter";
import { adaptPrediction } from "./predictionAdapter";
import { adaptWeather } from "./weatherAdapter";

export const getCurrentAQI = async (city) => {
    try {
        const response = await apiClient.get(`/currentAQI?city=${encodeURIComponent(city)}`);
        return adaptCurrentAQI(response.data);
    } catch (error) {
        throw new Error(error.response?.data?.detail || "Failed to fetch current AQI");
    }
};

export const getCurrentAQIByLocation = async (lat, lon) => {
    try {
        const geoResponse = await axios.get(
            `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lon}&email=contact@aqi-platform.com`,
            {
                headers: {
                    "Accept-Language": "en"
                }
            }
        );
        const geoData = geoResponse.data;
        const city = geoData.address.city || 
                     geoData.address.town || 
                     geoData.address.village || 
                     geoData.address.suburb || 
                     "Delhi";
                     
        return getCurrentAQI(city);
    } catch (error) {
        throw new Error("Location geocoding failed");
    }
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
        apiClient.post(`/predictAQI`, {
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
        .then(res => ({ ...res.data, horizon: h }))
        .catch(() => ({ horizon: h, predicted_aqi: null }))
    );

    const responses = await Promise.all(promises);
    return adaptPrediction(responses, currentAqi);
};

export const getWeather = async (city) => {
    try {
        const response = await apiClient.get(`/weather?city=${encodeURIComponent(city)}`);
        return adaptWeather(response.data);
    } catch (error) {
        throw new Error(error.response?.data?.detail || "Failed to fetch weather");
    }
};

export const getWeatherByLocation = async (lat, lon) => {
    try {
        const geoResponse = await axios.get(
            `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lon}&email=contact@aqi-platform.com`,
            {
                headers: {
                    "Accept-Language": "en"
                }
            }
        );
        const geoData = geoResponse.data;
        const city = geoData.address.city || 
                     geoData.address.town || 
                     geoData.address.village || 
                     geoData.address.suburb || 
                     "Delhi";
                     
        return getWeather(city);
    } catch (error) {
        throw new Error("Location geocoding failed");
    }
};

export const getExposureAnalytics = async (city) => {
    try {
        const response = await apiClient.get(`/exposure?city=${encodeURIComponent(city)}`);
        return response.data;
    } catch (error) {
        throw new Error(error.response?.data?.detail || "Failed to fetch exposure analytics");
    }
};

export const getRoute = async (source, destination, city = null) => {
    const body = {
        start_point: source,
        destination: destination
    };
    if (city) {
        body.city = city;
    }

    try {
        const response = await apiClient.post(`/getRoute`, body);
        return response.data;
    } catch (error) {
        throw new Error(error.response?.data?.detail || "Failed to optimize route");
    }
};

export const getHealthInsights = async (city, options = {}) => {
    try {
        const config = options.signal ? { signal: options.signal } : {};
        const response = await apiClient.get(`/getHealthInsights?city=${encodeURIComponent(city)}`, config);
        return response.data;
    } catch (error) {
        throw new Error(error.response?.data?.detail || "Failed to fetch health insights");
    }
};

export const getSafeWindow = async (payload, options = {}) => {
    try {
        const config = options.signal ? { signal: options.signal } : {};
        const response = await apiClient.post(`/getSafeWindow`, payload, config);
        return response.data;
    } catch (error) {
        throw new Error(error.response?.data?.detail || "Failed to calculate safe outdoor window");
    }
};
