import React, { createContext, useContext, useState, useEffect } from "react";
import apiClient from "../services/apiClient";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
    const [user, setUser] = useState(null);
    const [token, setToken] = useState(() => localStorage.getItem("token") || null);
    const [loading, setLoading] = useState(true);

    const fetchProfile = async () => {
        try {
            const res = await apiClient.get(`/auth/profile`);
            setUser(res.data);
            return res.data;
        } catch (err) {
            console.error("Failed to load user profile:", err);
            // apiClient's interceptor will handle the 401 logout if token is invalid
        }
        return null;
    };

    useEffect(() => {
        const initializeAuth = async () => {
            if (token) {
                await fetchProfile();
            }
            setLoading(false);
        };
        initializeAuth();
    }, [token]);

    const handleLoginSuccess = (accessToken) => {
        setToken(accessToken);
        localStorage.setItem("token", accessToken);
    };

    const handleLogout = () => {
        setToken(null);
        setUser(null);
        localStorage.removeItem("token");
    };

    const login = async (email, password) => {
        try {
            const res = await apiClient.post(`/auth/login`, { email, password });
            handleLoginSuccess(res.data.access_token);
            return await fetchProfile();
        } catch (error) {
            throw new Error(error.response?.data?.detail || "Invalid email or password");
        }
    };

    const register = async (email, password, name, city, ageGroup, activity, healthConditions, notifications) => {
        try {
            const res = await apiClient.post(`/auth/register`, {
                email,
                password,
                name: name || null,
                city: city || null,
                age_group: ageGroup || null,
                outdoor_activity: activity || null,
                health_conditions: healthConditions || [],
                notifications: notifications || null
            });
            handleLoginSuccess(res.data.access_token);
            return await fetchProfile();
        } catch (error) {
            throw new Error(error.response?.data?.detail || "Registration failed");
        }
    };

    const googleLogin = async (idToken) => {
        try {
            const res = await apiClient.post(`/auth/google-login`, { id_token: idToken });
            handleLoginSuccess(res.data.access_token);
            return await fetchProfile();
        } catch (error) {
            throw new Error(error.response?.data?.detail || "Google authentication failed");
        }
    };

    const updateProfile = async (fields) => {
        if (!token) return;
        const bodyPayload = {
            full_name: fields.fullName !== undefined ? fields.fullName : undefined,
            city: fields.city !== undefined ? fields.city : undefined,
            age_group: fields.ageGroup !== undefined ? fields.ageGroup : undefined,
            outdoor_activity: fields.outdoorActivity !== undefined ? fields.outdoorActivity : undefined,
            health_conditions: fields.healthConditions !== undefined ? fields.healthConditions : undefined,
            notifications: fields.notifications !== undefined ? fields.notifications : undefined,
        };

        // Filter out undefined keys so we do partial updates if needed
        Object.keys(bodyPayload).forEach(key => bodyPayload[key] === undefined && delete bodyPayload[key]);

        try {
            const res = await apiClient.put(`/auth/profile`, bodyPayload);
            setUser(res.data);
            return res.data;
        } catch (error) {
            throw new Error(error.response?.data?.detail || "Failed to update profile");
        }
    };

    const needsOnboarding = user !== null && user.preferences_completed === false;

    return (
        <AuthContext.Provider value={{ user, token, loading, login, register, logout: handleLogout, googleLogin, updateProfile, needsOnboarding }}>
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    const context = useContext(AuthContext);
    if (!context) {
        throw new Error("useAuth must be used within an AuthProvider");
    }
    return context;
}
