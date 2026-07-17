import React from "react";
import { useAuth } from "../context/AuthContext";
import "./Profile.css";

function Profile() {
  const { user } = useAuth();

  if (!user) {
    return (
      <div className="card">
        <h2>👤 My Profile</h2>
        <hr />
        <p>Please log in to view your profile.</p>
      </div>
    );
  }

  const name = user.full_name || "N/A";
  const email = user.email || "N/A";
  const city = user.city || "N/A";
  const ageGroup = user.age_group || "N/A";
  const activity = user.outdoor_activity || "N/A";
  const health = user.health_conditions || [];

  const formatHealth = (h) => {
    return h.split("_").map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()).join(" ");
  };

  return (
    <div className="card profile-card">
      <div className="profile-avatar">
        {name !== "N/A" ? name.charAt(0).toUpperCase() : email.charAt(0).toUpperCase()}
      </div>

      <h2>👤 My Profile</h2>
      <hr />

      <div className="profile-item">
        <span>👤 Name</span>
        <span>{name}</span>
      </div>

      <div className="profile-item">
        <span>📧 Email</span>
        <span>{email}</span>
      </div>

      <div className="profile-item">
        <span>📍 City</span>
        <span>{city}</span>
      </div>

      <div className="profile-item">
        <span>🎂 Age Group</span>
        <span>{ageGroup}</span>
      </div>

      <div className="profile-item">
        <span>🏃 Outdoor Activity</span>
        <span>{activity}</span>
      </div>

      <h3>🩺 Health Conditions</h3>
      <ul className="profile-list">
        {health.length ? (
          health.map((item, index) => (
            <li key={index}>{formatHealth(item)}</li>
          ))
        ) : (
          <li>No health conditions added</li>
        )}
      </ul>

      <h3>🔔 Notifications</h3>
      <ul className="profile-list">
        {user.notifications?.aqi_alerts && <li>AQI Alerts</li>}
        {user.notifications?.safe_window && <li>Safe Outdoor Window</li>}
        {user.notifications?.daily_summary && <li>Daily AQI Summary</li>}
        {(!user.notifications || (!user.notifications.aqi_alerts && !user.notifications.safe_window && !user.notifications.daily_summary)) && (
          <li>No notifications enabled</li>
        )}
      </ul>

      <div className="profile-item">
        <span>📅 Account Created</span>
        <span>{user.created_at ? new Date(user.created_at).toLocaleString() : "N/A"}</span>
      </div>

      <div className="profile-item">
        <span>🕒 Last Login</span>
        <span>{user.last_login ? new Date(user.last_login).toLocaleString() : "N/A"}</span>
      </div>
    </div>
  );
}

export default Profile;