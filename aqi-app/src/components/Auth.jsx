import React, { useState, useEffect, useCallback, useRef } from "react";
import { useAuth } from "../context/AuthContext";
import "./Auth.css";

const GOOGLE_CLIENT_ID = process.env.REACT_APP_GOOGLE_CLIENT_ID;

function Auth() {
  const { login, register, googleLogin } = useAuth();

  const [isLogin, setIsLogin] = useState(true);
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [message, setMessage] = useState("");
  const [messageType, setMessageType] = useState("");

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [city, setCity] = useState("");
  const [ageGroup, setAgeGroup] = useState("");
  const [activity, setActivity] = useState("");
  const [health, setHealth] = useState([]);
  const [notifications, setNotifications] = useState([]);

  const healthOptions = [
    "Asthma",
    "Allergy",
    "Heart Disease",
    "Lung Disease"
  ];

  const notificationOptions = [
    "AQI Alerts",
    "Safe Outdoor Window",
    "Daily AQI Summary"
  ];

  const handleGoogleCredentialResponse = useCallback(async (response) => {
    if (!GOOGLE_CLIENT_ID) {
      setMessage("Google Sign-In is unavailable (Client ID not configured).");
      setMessageType("error");
      return;
    }
    try {
      setLoading(true);
      setMessage("");
      await googleLogin(response.credential);
      setMessage("Login Successful.");
      setMessageType("success");
    } catch (err) {
      console.error(err);
      setMessage(err.message || "Google authentication failed.");
      setMessageType("error");
    } finally {
      setLoading(false);
    }
  }, [googleLogin]);

  const credentialHandlerRef = useRef(handleGoogleCredentialResponse);
  useEffect(() => {
    credentialHandlerRef.current = handleGoogleCredentialResponse;
  });

  // Dynamic injection & initialization of Google Identity Services SDK
  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) {
      console.warn("Google Sign-In is disabled: REACT_APP_GOOGLE_CLIENT_ID is not configured.");
      return;
    }

    const initGoogle = () => {
      if (window.google?.accounts?.id) {
        window.google.accounts.id.initialize({
          client_id: GOOGLE_CLIENT_ID,
          callback: (res) => {
            if (credentialHandlerRef.current) {
              credentialHandlerRef.current(res);
            }
          },
        });
        const container = document.getElementById("google-signin-button");
        if (container) {
          window.google.accounts.id.renderButton(container, {
            theme: "outline",
            size: "large",
            width: 370,
            shape: "rectangular",
            text: "signin_with",
            logo_alignment: "left",
          });
        }
      }
    };

    if (window.google?.accounts?.id) {
      initGoogle();
    } else {
      const script = document.createElement("script");
      script.src = "https://accounts.google.com/gsi/client";
      script.async = true;
      script.defer = true;
      script.onload = initGoogle;
      document.body.appendChild(script);
    }
  }, []);

  const toggleHealth = (item) => {
    setHealth((prev) =>
      prev.includes(item)
        ? prev.filter((h) => h !== item)
        : [...prev, item]
    );
  };

  const toggleNotification = (item) => {
    setNotifications((prev) =>
      prev.includes(item)
        ? prev.filter((n) => n !== item)
        : [...prev, item]
    );
  };

  const validateForm = () => {
    if (!email.trim()) {
      return "Email Address is required.";
    }
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
      return "Please enter a valid email address.";
    }
    if (!password) {
      return "Password is required.";
    }
    if (password.length < 6) {
      return "Password must be at least 6 characters.";
    }
    if (!isLogin) {
      if (!name.trim()) {
        return "Name is required.";
      }
    }
    return "";
  };

  const handleSubmit = async () => {
    const validation = validateForm();
    if (validation) {
      setMessage(validation);
      setMessageType("error");
      return;
    }

    try {
      setLoading(true);
      setMessage("");

      if (isLogin) {
        await login(email.trim(), password);
        setMessage("Login Successful.");
        setMessageType("success");
      } else {
        const mappedHealth = health.map(h => h.toUpperCase().replace(" ", "_"));
        const notificationsPayload = {
          aqi_alerts: notifications.includes("AQI Alerts"),
          safe_window: notifications.includes("Safe Outdoor Window"),
          daily_summary: notifications.includes("Daily AQI Summary")
        };
        await register(
          email.trim(),
          password,
          name.trim(),
          city.trim() || null,
          ageGroup || null,
          activity || null,
          mappedHealth,
          notificationsPayload
        );
        setMessage("Registration Successful. Automatically logging in...");
        setMessageType("success");
      }
    } catch (err) {
      console.error(err);
      setMessage(err.message || "Authentication failed.");
      setMessageType("error");
    } finally {
      setLoading(false);
    }
  };


  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-header">
          <h2>{isLogin ? "Welcome Back" : "Create Account"}</h2>
          <p className="auth-sub">
            {isLogin
              ? "Sign in to access your personalized AQI dashboard."
              : "Sign up to track and minimize personal exposure risk."}
          </p>
        </div>

        {message && (
          <div className={`auth-message ${messageType}`} role="alert">
            {message}
          </div>
        )}

        {!isLogin && (
          <>
            <div className="input-group">
              <label htmlFor="reg-name">Name</label>
              <div className="input-wrapper">
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="input-icon">
                  <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/>
                  <circle cx="12" cy="7" r="4"/>
                </svg>
                <input
                  id="reg-name"
                  type="text"
                  placeholder="Enter your full name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </div>
            </div>

            <div className="input-group">
              <label htmlFor="reg-city">City</label>
              <div className="input-wrapper">
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="input-icon">
                  <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/>
                  <circle cx="12" cy="10" r="3"/>
                </svg>
                <input
                  id="reg-city"
                  type="text"
                  placeholder="e.g. Delhi, Mumbai"
                  value={city}
                  onChange={(e) => setCity(e.target.value)}
                />
              </div>
            </div>

            <div className="input-group">
              <label htmlFor="reg-age">Age Group</label>
              <div className="input-wrapper">
                <select
                  id="reg-age"
                  value={ageGroup}
                  onChange={(e) => setAgeGroup(e.target.value)}
                >
                  <option value="">Select Age Group</option>
                  <option>Below 18</option>
                  <option>18-35</option>
                  <option>36-60</option>
                  <option>Above 60</option>
                </select>
              </div>
            </div>

            <div className="input-group">
              <label htmlFor="reg-activity">Outdoor Activity</label>
              <div className="input-wrapper">
                <select
                  id="reg-activity"
                  value={activity}
                  onChange={(e) => setActivity(e.target.value)}
                >
                  <option value="">Select Activity</option>
                  <option>Rarely</option>
                  <option>Sometimes</option>
                  <option>Daily</option>
                  <option>Outdoor Worker</option>
                </select>
              </div>
            </div>

            <div className="input-group">
              <label>Health Conditions</label>
              <div className="checkbox-group">
                {healthOptions.map((item) => (
                  <button
                    key={item}
                    type="button"
                    className={`checkbox-btn ${
                      health.includes(item) ? "active" : ""
                    }`}
                    onClick={() => toggleHealth(item)}
                  >
                    {health.includes(item) && (
                      <span className="checkmark-icon" style={{ marginRight: "6px" }}>✓</span>
                    )}
                    {item}
                  </button>
                ))}
              </div>
            </div>

            <div className="input-group">
              <label>Alert Notifications</label>
              <div className="checkbox-group">
                {notificationOptions.map((item) => (
                  <button
                    key={item}
                    type="button"
                    className={`checkbox-btn ${
                      notifications.includes(item) ? "active" : ""
                    }`}
                    onClick={() => toggleNotification(item)}
                  >
                    {notifications.includes(item) && (
                      <span className="checkmark-icon" style={{ marginRight: "6px" }}>✓</span>
                    )}
                    {item}
                  </button>
                ))}
              </div>
            </div>
          </>
        )}

        <div className="input-group">
          <label htmlFor="auth-email">Email Address</label>
          <div className="input-wrapper">
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="input-icon">
              <rect width="20" height="16" x="2" y="4" rx="2"/>
              <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>
            </svg>
            <input
              id="auth-email"
              type="email"
              placeholder="name@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
        </div>

        <div className="input-group">
          <label htmlFor="auth-password">Password</label>
          <div className="input-wrapper">
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="input-icon">
              <rect width="18" height="11" x="3" y="11" rx="2" ry="2"/>
              <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
            </svg>
            <input
              id="auth-password"
              type={showPassword ? "text" : "password"}
              placeholder="Enter password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <button
              type="button"
              className="show-password-btn"
              onClick={() => setShowPassword(!showPassword)}
            >
              {showPassword ? "🙈" : "👁"}
            </button>
          </div>
        </div>

        <button
          className="auth-button"
          onClick={handleSubmit}
          disabled={loading}
        >
          {loading && <span className="spinner"></span>}
          {isLogin ? "Sign In" : "Create Account"}
        </button>

        <div className="divider">
          <span>OR</span>
        </div>

        <div className="social-login-group">
          <div id="google-signin-button" className="google-signin-container"></div>
        </div>

        <div className="auth-footer">
          <p>
            {isLogin ? "Don't have an account? " : "Already have an account? "}
            <button
              type="button"
              className="switch-button"
              onClick={() => {
                setIsLogin(!isLogin);
                setMessage("");
                setEmail("");
                setPassword("");
              }}
            >
              {isLogin ? "Register →" : "Login →"}
            </button>
          </p>
        </div>
      </div>
    </div>
  );
}

export default Auth;