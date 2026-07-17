import React, { useState, useEffect } from "react";

import {
    MapContainer,
    TileLayer,
    Marker,
    Popup,
    Polyline,
    useMap
} from "react-leaflet";

import L from "leaflet";

import "leaflet/dist/leaflet.css";

import { getRoute } from "../services/backendApi";

import "./MapView.css";


// ===========================================
// Custom Marker Icons
// ===========================================

const sourceIcon = new L.Icon({

    iconUrl:
        "https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-green.png",

    shadowUrl:
        "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",

    iconSize: [25, 41],

    iconAnchor: [12, 41],

});

const destinationIcon = new L.Icon({

    iconUrl:
        "https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-red.png",

    shadowUrl:
        "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",

    iconSize: [25, 41],

    iconAnchor: [12, 41],

});


// ===========================================
// Route color map
// ===========================================



const SEGMENT_COLORS = {
    green: "#22c55e",
    yellow: "#f59e0b",
    orange: "#f97316",
    red: "#ef4444",
    purple: "#7e22ce",
    maroon: "#800000"
};

function getSegmentColor(color) {
    return SEGMENT_COLORS[color] || color || "#2563eb";
}

function getScoreColor(score) {
    if (score >= 75) return "#22c55e";
    if (score >= 50) return "#f59e0b";
    return "#ef4444";
}


// ===========================================
// Automatically Fly/Fit Map to Route/Bounds
// ===========================================

function MapController({ routeCoords, sourceCoords }) {
    const map = useMap();

    useEffect(() => {
        if (routeCoords && routeCoords.length > 0) {
            const bounds = L.latLngBounds(routeCoords);
            map.fitBounds(bounds, {
                padding: [50, 50],
                maxZoom: 15
            });
        } else if (sourceCoords) {
            map.setView(
                [sourceCoords.lat, sourceCoords.lon],
                12
            );
        }
    }, [map, routeCoords, sourceCoords]);

    return null;
}


// ===========================================
// Main Component
// ===========================================

function MapView() {

    const [source, setSource] = useState("");

    const [destination, setDestination] = useState("");

    const [sourceCoords, setSourceCoords] = useState(null);

    const [destinationCoords, setDestinationCoords] = useState(null);

    const [loading, setLoading] = useState(false);

    const [error, setError] = useState("");

    const [routeResponse, setRouteResponse] = useState(null);


    // =======================================
    // Current Location
    // =======================================

    const useCurrentLocation = () => {

        if (!navigator.geolocation) {

            alert("Geolocation not supported");

            return;

        }

        navigator.geolocation.getCurrentPosition(

            (position) => {

                const latitude = position.coords.latitude;

                const longitude = position.coords.longitude;

                setSource(`${latitude}, ${longitude}`);

            },

            () => {

                alert("Unable to get current location");

            }

        );

    };


    // =======================================
    // Find Route (Backend Integration)
    // =======================================

    const findRoutes = async () => {

        try {

            setLoading(true);

            setError("");

            setRouteResponse(null);

            setSourceCoords(null);

            setDestinationCoords(null);


            if (!source.trim() || !destination.trim()) {

                setError("Please enter both source and destination.");

                setLoading(false);

                return;

            }


            const data = await getRoute(source, destination);


            if (!data.routes || data.routes.length === 0) {

                setError("No routes found. Please try different locations.");

                setLoading(false);

                return;

            }


            setRouteResponse(data);


            // Extract coordinates from first route for map centering
            const firstRoute = data.routes[0];

            if (firstRoute.segments && firstRoute.segments.length > 0) {

                const allCoords = firstRoute.segments.flatMap(s => s.coordinates || []);

                if (allCoords.length > 0) {

                    setSourceCoords({ lat: allCoords[0][0], lon: allCoords[0][1] });

                    setDestinationCoords({

                        lat: allCoords[allCoords.length - 1][0],

                        lon: allCoords[allCoords.length - 1][1]

                    });

                }

            }

        }

        catch (err) {

            console.error("Route optimization error:", err);

            setError(

                err.message || "Unable to calculate route. Please check your connection and try again."

            );

        }

        finally {

            setLoading(false);

        }

    };





    // Get candidate routes from response
    const candidateRoutes = routeResponse?.candidate_routes || routeResponse?.routes || [];
    const recommendedId = routeResponse?.recommended?.recommended_route_id || null;

    // Find recommended route details
    const recommendedRoute = candidateRoutes.find(r => r.route_id && r.route_id === recommendedId) || candidateRoutes[0] || null;

    // Find alternative routes (excluding recommended)
    const alternativeRoutes = candidateRoutes.filter(r => r !== recommendedRoute).slice(0, 2);

    const recommendedRouteCoords = recommendedRoute?.segments?.flatMap(s => s.coordinates || []) || [];


    return (

        <div className="card map-view-card">

            <div className="map-header">

                <div>

                    <h2>🌿 AQI Route Planner</h2>

                    <p>

                        Find the safest route based on air quality — powered by Route Optimization Engine V2.

                    </p>

                </div>

            </div>


            {/* ======================================
                SEARCH SECTION
            ======================================= */}

            <div className="route-search">

                <input

                    type="text"

                    placeholder="📍 Enter Source"

                    value={source}

                    onChange={(e) =>

                        setSource(e.target.value)

                    }

                />



                <input

                    type="text"

                    placeholder="🏁 Enter Destination"

                    value={destination}

                    onChange={(e) =>

                        setDestination(

                            e.target.value

                        )

                    }

                />

            </div>


            <div className="route-buttons">

                <button

                    className="location-btn"

                    onClick={useCurrentLocation}

                >

                    📍 Use Current Location

                </button>



                <button

                    className="route-btn"

                    onClick={findRoutes}

                    disabled={loading}

                >

                    {

                        loading

                            ? "🔍 Optimizing Route..."

                            : "🌿 Find Cleanest Route"

                    }

                </button>

            </div>


            {/* ======================================
                ERROR
            ======================================= */}

            {

                error &&

                <div className="route-error">

                    ⚠ {error}

                </div>

            }


            {/* ======================================
                LOADING STATE
            ======================================= */}

            {

                loading &&

                <div className="route-loading">

                    <div className="route-loading-spinner" />

                    <p>Analyzing air quality along multiple routes...</p>

                </div>

            }


            {/* ======================================
                RECOMMENDED ROUTE CARD
            ======================================= */}

            {

                recommendedRoute && !loading &&

                <div className="route-recommended-card">

                    <div className="route-recommended-badge">

                        ⭐ Recommended Route

                    </div>

                    <div className="route-grid">

                        <div>

                            <span>

                                Score

                            </span>

                            <h4 style={{ color: getScoreColor(recommendedRoute.score?.total_score) }}>

                                {recommendedRoute.score?.total_score?.toFixed(1) ?? "N/A"}

                            </h4>

                        </div>

                        <div>

                            <span>

                                AQI

                            </span>

                            <h4>

                                {recommendedRoute.average_route_aqi?.toFixed(0) ?? "N/A"}

                            </h4>

                        </div>

                        <div>

                            <span>

                                Distance

                            </span>

                            <h4>

                                {recommendedRoute.distance_km?.toFixed(2) ?? "N/A"} km

                            </h4>

                        </div>

                        <div>

                            <span>

                                Duration

                            </span>

                            <h4>

                                {recommendedRoute.estimated_time_mins?.toFixed(0) ?? "N/A"} min

                            </h4>

                        </div>

                    </div>

                    <div className="route-details-row">

                        <div className="route-detail-item">

                            <span>Dominant Pollutant</span>

                            <strong>{recommendedRoute.diagnostic?.dominant_pollutant ?? recommendedRoute.dominant_pollutant ?? "—"}</strong>

                        </div>

                        <div className="route-detail-item">

                            <span>Exposure Rating</span>

                            <strong>{recommendedRoute.exposure_rating ?? "—"}</strong>

                        </div>

                        <div className="route-detail-item">

                            <span>Max AQI</span>

                            <strong>{recommendedRoute.maximum_aqi?.toFixed(0) ?? "N/A"}</strong>

                        </div>

                        <div className="route-detail-item">

                            <span>Confidence</span>

                            <strong>{routeResponse?.recommended?.confidence ?? recommendedRoute.confidence ?? "—"}</strong>

                        </div>

                    </div>

                    {routeResponse?.recommended?.reasoning && routeResponse.recommended.reasoning.length > 0 &&

                        <div className="route-reasoning">

                            <strong>Why this route?</strong>

                            <ul>

                                {routeResponse.recommended.reasoning.map((r, i) => (

                                    <li key={i}>{r}</li>

                                ))}

                            </ul>

                        </div>

                    }

                </div>

            }


            {/* ======================================
                ALTERNATIVE ROUTES
            ======================================= */}

            {

                alternativeRoutes.length > 0 && !loading &&

                <div className="route-alternatives">

                    <h3>🔀 Alternative Routes</h3>

                    <div className="route-alt-grid">

                        {alternativeRoutes.map((alt) => (

                            <div key={alt.route_id} className="route-alt-card">

                                <div className="route-alt-header">

                                    <span className="route-alt-name">{alt.route_name || alt.route_id}</span>

                                    <span className="route-alt-score" style={{ color: getScoreColor(alt.score?.total_score) }}>

                                        {alt.score?.total_score?.toFixed(1) ?? "N/A"}

                                    </span>

                                </div>

                                <div className="route-alt-stats">

                                    <span>{alt.distance_km?.toFixed(2) ?? "N/A"} km</span>

                                    <span>{alt.estimated_time_mins?.toFixed(0) ?? "N/A"} min</span>

                                    <span>AQI: {alt.average_route_aqi?.toFixed(0) ?? "N/A"}</span>

                                </div>

                            </div>

                        ))}

                    </div>

                </div>

            }


            {/* ======================================
                TRADE-OFFS
            ======================================= */}

            {

                routeResponse?.recommended?.trade_offs &&

                routeResponse.recommended.trade_offs.length > 0 && !loading &&

                <div className="route-tradeoffs">

                    <h3>⚖️ Trade-offs</h3>

                    <div className="route-tradeoff-list">

                        {routeResponse.recommended.trade_offs.map((t, i) => (

                            <div key={i} className="route-tradeoff-item">

                                <p>{t.explanation}</p>

                                <div className="route-tradeoff-metrics">

                                    {t.time_diff_mins !== 0 &&

                                        <span className={t.time_diff_mins > 0 ? "metric-negative" : "metric-positive"}>

                                            {t.time_diff_mins > 0 ? "+" : ""}{t.time_diff_mins?.toFixed(1)} min

                                        </span>

                                    }

                                    {t.aqi_improvement_pct !== 0 &&

                                        <span className={t.aqi_improvement_pct > 0 ? "metric-positive" : "metric-negative"}>

                                            {t.aqi_improvement_pct > 0 ? "+" : ""}{t.aqi_improvement_pct?.toFixed(1)}% AQI

                                        </span>

                                    }

                                </div>

                            </div>

                        ))}

                    </div>

                </div>

            }


            {/* ======================================
                MAP
            ======================================= */}

            <div className="map-container-wrapper">

                <MapContainer

                    center={

                        sourceCoords

                            ? [sourceCoords.lat, sourceCoords.lon]

                            : [20.5937, 78.9629]

                    }

                    zoom={10}

                    className="leaflet-map"

                >

                    <MapController
                        routeCoords={recommendedRouteCoords}
                        sourceCoords={sourceCoords}
                    />


                    <TileLayer

                        attribution='&copy; OpenStreetMap contributors'

                        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"

                    />


                    {/* SOURCE */}

                    {

                        sourceCoords &&

                        <Marker

                            position={[sourceCoords.lat, sourceCoords.lon]}

                            icon={sourceIcon}

                        >

                            <Popup>

                                <b>📍 Source</b><br />

                                {source}

                            </Popup>

                        </Marker>

                    }


                    {/* DESTINATION */}

                    {

                        destinationCoords &&

                        <Marker

                            position={[destinationCoords.lat, destinationCoords.lon]}

                            icon={destinationIcon}

                        >

                            <Popup>

                                <b>🏁 Destination</b><br />

                                {destination}

                            </Popup>

                        </Marker>

                    }


                    {/* RECOMMENDED ROUTE */}

                    {

                        recommendedRoute &&
                        recommendedRoute.segments?.map((segment, index) => {
                            const positions = segment.coordinates || [];
                            if (positions.length === 0) return null;
                            return (
                                <Polyline
                                    key={`recommended-${index}`}
                                    positions={positions}
                                    pathOptions={{
                                        color: getSegmentColor(segment.color),
                                        weight: 8,
                                        opacity: 0.9
                                    }}
                                />
                            );
                        })

                    }


                    {/* ALTERNATIVE ROUTE 1 */}

                    {

                        alternativeRoutes[0] &&
                        alternativeRoutes[0].segments?.map((segment, index) => {
                            const positions = segment.coordinates || [];
                            if (positions.length === 0) return null;
                            return (
                                <Polyline
                                    key={`alt1-${index}`}
                                    positions={positions}
                                    pathOptions={{
                                        color: getSegmentColor(segment.color),
                                        weight: 5,
                                        opacity: 0.7,
                                        dashArray: "10, 8"
                                    }}
                                />
                            );
                        })

                    }


                    {/* ALTERNATIVE ROUTE 2 */}

                    {

                        alternativeRoutes[1] &&
                        alternativeRoutes[1].segments?.map((segment, index) => {
                            const positions = segment.coordinates || [];
                            if (positions.length === 0) return null;
                            return (
                                <Polyline
                                    key={`alt2-${index}`}
                                    positions={positions}
                                    pathOptions={{
                                        color: getSegmentColor(segment.color),
                                        weight: 5,
                                        opacity: 0.7,
                                        dashArray: "10, 8"
                                    }}
                                />
                            );
                        })

                    }


                </MapContainer>

            </div>

        </div>

    );

}

export default MapView;