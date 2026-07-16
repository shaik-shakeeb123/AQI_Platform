import React from "react";

import { useAuth } from "../context/AuthContext";

import "./PollutionTips.css";

function PollutionTips({ aqi }) {

  const { user, loading } = useAuth();

  const userData = user ? {
    ageGroup: user.age_group || "Adult",
    activity: user.outdoor_activity || "Moderate",
    city: user.city || "",
    health: user.health_conditions || []
  } : null;

  if (loading) {

    return (

      <div className="pollution-card">

        <h2>

          🌱 Personalized Eco Tips

        </h2>

        <p>

          Loading recommendations...

        </p>

      </div>

    );

  }

  const age =

    userData?.ageGroup ||

    "Adult";

  const activity =

    userData?.activity ||

    "Moderate";

  const city =

    userData?.city ||

    "Your City";

  const health =

    userData?.health ||

    [];

  let title = "";

  let color = "";

  let message = "";

  let tips = [];

  if (aqi <= 50) {

    title =

      "🌿 Great Air Quality";

    color =

      "#22c55e";

    message =

      "Air quality is excellent. Continue your eco-friendly habits.";

    tips = [

      "Walk or cycle for short distances.",

      "Maintain green surroundings.",

      "Plant more indoor plants.",

      "Save electricity whenever possible."

    ];

  }

  else if (aqi <= 100) {

    title =

      "🙂 Moderate Pollution";

    color =

      "#eab308";

    message =

      "Small actions today can prevent pollution from increasing.";

    tips = [

      "Use public transport.",

      "Reduce vehicle idling.",

      "Choose walking whenever possible.",

      "Prefer green routes."

    ];

  }

  else if (aqi <= 150) {

    title =

      "🟠 Pollution Reduction Needed";

    color =

      "#f97316";

    message =

      "Pollution is increasing. Collective action matters.";

    tips = [

      "Carpool whenever possible.",

      "Avoid burning waste.",

      "Limit unnecessary travel.",

      "Use energy-efficient appliances."

    ];

  }

  else {

    title =

      "🔴 High Pollution Alert";

    color =

      "#ef4444";

    message =

      "Urgent action is required to reduce pollution.";

    tips = [

      "Avoid private vehicle use.",

      "Stay indoors during peak pollution hours.",

      "Use an air purifier if available.",

      "Spread awareness about pollution reduction."

    ];

  }

  if (activity === "Daily" || activity === "Outdoor Worker") {

    tips.push(

      "🏃 Prefer walking or cycling over short bike rides."

    );

  }

  if (age === "Above 60") {

    tips.push(

      "👴 Avoid crowded and traffic-heavy areas."

    );

  }

  if (age === "Below 18") {

    tips.push(

      "👶 Play in parks away from busy roads."

    );

  }

  if (

    health.includes("Asthma") ||

    health.includes("Allergy")

  ) {

    tips.push(

      "😷 Carry an N95 mask whenever you go outdoors."

    );

  }
    return (

    <div className="pollution-card">

      <h2>

        🌱 Personalized Eco Tips

      </h2>

      <div

        className="pollution-status"

        style={{

          background: color

        }}

      >

        {title}

      </div>

      <div className="pollution-profile">

        <div className="profile-item">

          <span>📍</span>

          <div>

            <strong>City</strong>

            <p>{city}</p>

          </div>

        </div>

        <div className="profile-item">

          <span>👤</span>

          <div>

            <strong>Age Group</strong>

            <p>{age}</p>

          </div>

        </div>

        <div className="profile-item">

          <span>🏃</span>

          <div>

            <strong>Activity</strong>

            <p>{activity}</p>

          </div>

        </div>

      </div>

      <h3 className="tips-title">

        💡 Recommended Actions

      </h3>

      <div className="tips-grid">

        {

          tips.map((tip, index) => (

            <div

              key={index}

              className="tip-card"

            >

              <span className="tip-icon">

                ✅

              </span>

              <span>

                {tip}

              </span>

            </div>

          ))

        }

      </div>

      {

        health.length > 0 && (

          <div className="health-box">

            <h3>

              ❤️ Health Conditions

            </h3>

            <div className="health-list">

              {

                health.map((item, index) => (

                  <span

                    key={index}

                    className="health-tag"

                  >

                    {item}

                  </span>

                ))

              }

            </div>

          </div>

        )

      }

      <div className="eco-message">

        🌍

        <p>

          {message}

        </p>

      </div>

    </div>

  );

}

export default PollutionTips;