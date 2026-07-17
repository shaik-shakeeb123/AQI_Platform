import React, { useState } from "react";
import { useAuth } from "../context/AuthContext";
import "./CompleteProfile.css";

function CompleteProfile() {
  const { updateProfile, logout } = useAuth();
  const [city, setCity] = useState("");
  const [ageGroup, setAgeGroup] = useState("");
  const [activity, setActivity] = useState("");
  const [health, setHealth] = useState([]);
  const [notifications, setNotifications] = useState([
    "AQI Alerts",
    "Safe Outdoor Window",
    "Daily AQI Summary"
  ]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const healthOptions = [
    "Asthma",
    "Allergy",
    "Heart Disease",
    "Lung Disease",
    "Other"
  ];

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

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!city.trim()) {
      setError("City is required.");
      return;
    }
    if (!ageGroup) {
      setError("Age Group is required.");
      return;
    }
    if (!activity) {
      setError("Outdoor Activity is required.");
      return;
    }

    try {
      setLoading(true);
      setError("");

      // Map health conditions array (represented as upper case for DB clean matching)
      const mappedHealth = health.map(h => h.toUpperCase().replace(" ", "_"));

      // Map notifications requests
      const notificationsPayload = {
        aqi_alerts: notifications.includes("AQI Alerts"),
        safe_window: notifications.includes("Safe Outdoor Window"),
        daily_summary: notifications.includes("Daily AQI Summary")
      };

      await updateProfile({
        city: city.trim(),
        ageGroup: ageGroup,
        outdoorActivity: activity,
        healthConditions: mappedHealth,
        notifications: notificationsPayload
      });
    } catch (err) {
      console.error(err);
      setError(err.message || "Failed to save profile preferences.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="onboarding-page">
      <div className="auth-card onboarding-card">
        <div className="auth-header">
          <h1>🌱 Complete Your AQI Profile</h1>
          <p>Help us customize your health insights, exposure alerts, and safe outdoor windows.</p>
        </div>

        {error && <div className="message error">{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className="input-group">
            <label>📍 Home City (Required)</label>
            <input
              type="text"
              placeholder="e.g. Mumbai"
              value={city}
              onChange={(e) => setCity(e.target.value)}
              required
            />
          </div>

          <div className="input-group">
            <label>🎂 Age Group (Required)</label>
            <select
              value={ageGroup}
              onChange={(e) => setAgeGroup(e.target.value)}
              required
            >
              <option value="">Select Age Group</option>
              <option>Below 18</option>
              <option>18-35</option>
              <option>36-60</option>
              <option>Above 60</option>
            </select>
          </div>

          <div className="input-group">
            <label>🏃 Outdoor Activity Frequency (Required)</label>
            <select
              value={activity}
              onChange={(e) => setActivity(e.target.value)}
              required
            >
              <option value="">Select Activity</option>
              <option>Rarely</option>
              <option>Sometimes</option>
              <option>Daily</option>
              <option>Outdoor Worker</option>
            </select>
          </div>

          <div className="input-group">
            <label>🩺 Health Conditions (Select all that apply)</label>
            <div className="checkbox-group">
              {healthOptions.map((item) => {
                const isSelected = health.includes(item);
                return (
                  <button
                    key={item}
                    type="button"
                    className={`checkbox-btn ${isSelected ? "active" : ""}`}
                    onClick={() => toggleHealth(item)}
                  >
                    {isSelected && <span className="checkmark-icon" style={{ marginRight: "6px", fontWeight: "bold" }}>✓</span>}
                    {item}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="input-group">
            <label>🔔 Notification Subscriptions (Default ON)</label>
            <div className="notification-toggle-list">
              <div className="notification-toggle-item">
                <div className="toggle-info">
                  <span className="toggle-icon">🔔</span>
                  <div className="toggle-text">
                    <span className="toggle-label">AQI Alerts</span>
                    <span className="toggle-description">Receive alerts when AQI becomes unhealthy.</span>
                  </div>
                </div>
                <label className="toggle-switch">
                  <input
                    type="checkbox"
                    checked={notifications.includes("AQI Alerts")}
                    onChange={() => toggleNotification("AQI Alerts")}
                  />
                  <span className="toggle-slider"></span>
                </label>
              </div>

              <div className="notification-toggle-item">
                <div className="toggle-info">
                  <span className="toggle-icon">🌿</span>
                  <div className="toggle-text">
                    <span className="toggle-label">Safe Outdoor Window</span>
                    <span className="toggle-description">Notify when outdoor air quality becomes safer.</span>
                  </div>
                </div>
                <label className="toggle-switch">
                  <input
                    type="checkbox"
                    checked={notifications.includes("Safe Outdoor Window")}
                    onChange={() => toggleNotification("Safe Outdoor Window")}
                  />
                  <span className="toggle-slider"></span>
                </label>
              </div>

              <div className="notification-toggle-item">
                <div className="toggle-info">
                  <span className="toggle-icon">📊</span>
                  <div className="toggle-text">
                    <span className="toggle-label">Daily AQI Summary</span>
                    <span className="toggle-description">Receive one AQI summary every day.</span>
                  </div>
                </div>
                <label className="toggle-switch">
                  <input
                    type="checkbox"
                    checked={notifications.includes("Daily AQI Summary")}
                    onChange={() => toggleNotification("Daily AQI Summary")}
                  />
                  <span className="toggle-slider"></span>
                </label>
              </div>
            </div>
          </div>

          <div className="button-group" style={{ display: "flex", gap: "12px", marginTop: "20px" }}>
            <button
              type="submit"
              className="auth-button"
              disabled={loading}
              style={{ flex: 2, marginTop: 0 }}
            >
              {loading ? "Saving Profile..." : "Save & Continue"}
            </button>
            <button
              type="button"
              className="auth-button"
              onClick={logout}
              style={{
                flex: 1,
                marginTop: 0,
                background: "rgba(239,68,68,0.15)",
                border: "1px solid rgba(239,68,68,0.35)",
                color: "#ef4444"
              }}
            >
              Logout
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default CompleteProfile;
