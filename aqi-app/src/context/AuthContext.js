import React, { createContext, useContext, useState, useEffect } from "react";

const AuthContext = createContext(null);

const BASE_URL = process.env.REACT_APP_API_URL || "";

export function AuthProvider({ children }) {
    const [user, setUser] = useState(null);
    const [token, setToken] = useState(() => localStorage.getItem("token") || null);
    const [loading, setLoading] = useState(true);

    const fetchProfile = async (accessToken) => {
        try {
            const res = await fetch(`${BASE_URL}/auth/profile`, {
                headers: {
                    "Authorization": `Bearer ${accessToken}`
                }
            });
            if (res.ok) {
                const profile = await res.json();
                setUser(profile);
                return profile;
            } else {
                // Token invalid or expired
                handleLogout();
            }
        } catch (err) {
            console.error("Failed to load user profile:", err);
        }
        return null;
    };

    useEffect(() => {
        const initializeAuth = async () => {
            if (token) {
                await fetchProfile(token);
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
        const res = await fetch(`${BASE_URL}/auth/login`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ email, password })
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Invalid email or password");
        }
        const data = await res.json();
        handleLoginSuccess(data.access_token);
        return await fetchProfile(data.access_token);
    };

    const register = async (email, password, name, city, ageGroup, activity, healthConditions, notifications) => {
        const res = await fetch(`${BASE_URL}/auth/register`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                email,
                password,
                name: name || null,
                city: city || null,
                age_group: ageGroup || null,
                outdoor_activity: activity || null,
                health_conditions: healthConditions || [],
                notifications: notifications || null
            })
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Registration failed");
        }
        const data = await res.json();
        handleLoginSuccess(data.access_token);
        return await fetchProfile(data.access_token);
    };

    const googleLogin = async (idToken) => {
        const res = await fetch(`${BASE_URL}/auth/google-login`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ id_token: idToken })
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Google authentication failed");
        }
        const data = await res.json();
        handleLoginSuccess(data.access_token);
        return await fetchProfile(data.access_token);
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

        const res = await fetch(`${BASE_URL}/auth/profile`, {
            method: "PUT",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${token}`
            },
            body: JSON.stringify(bodyPayload)
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Failed to update profile");
        }
        const updatedUser = await res.json();
        setUser(updatedUser);
        return updatedUser;
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
