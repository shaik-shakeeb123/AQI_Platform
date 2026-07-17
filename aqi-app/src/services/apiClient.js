import axios from "axios";

const BASE_URL = process.env.REACT_APP_API_URL;

if (!BASE_URL) {
    console.error("CRITICAL ERROR: REACT_APP_API_URL is missing. Please set this environment variable.");
}

const apiClient = axios.create({
    baseURL: BASE_URL || "",
    timeout: 8000,
});

apiClient.interceptors.request.use(
    (config) => {
        const token = localStorage.getItem("token");
        if (token) {
            config.headers.Authorization = `Bearer ${token}`;
        }
        return config;
    },
    (error) => Promise.reject(error)
);

apiClient.interceptors.response.use(
    (response) => response,
    (error) => {
        if (error.response && error.response.status === 401) {
            console.error("Authentication expired or unauthorized (401). Logging out...");
            localStorage.removeItem("token");
            // If the user isn't already on the login page, reload to trigger the auth flow.
            if (window.location.pathname !== "/") {
                window.location.href = "/";
            }
        }
        return Promise.reject(error);
    }
);

export default apiClient;
