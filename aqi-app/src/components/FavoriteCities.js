import React from "react";
import "./FavoriteCities.css";

function FavoriteCities({

    favorites = [],

    onSelect,

    selectedCity

}) {

    if (favorites.length === 0) {

        return (

            <div className="card favorite-card">

                <h2>

                    ⭐ Favorite Cities

                </h2>

                <div className="loading-text">

                    No favorite cities added.

                </div>

            </div>

        );

    }

    return (

        <div className="card favorite-card">

            <h2>

                ⭐ Favorite Cities

            </h2>

            <div className="fav-container">

                {

                    favorites.map((city) => (

                        <button

                            key={city}

                            type="button"

                            className={

                                city === selectedCity

                                    ? "fav-btn active"

                                    : "fav-btn"

                            }

                            onClick={() => onSelect(city)}

                        >

                            📍 {city}

                        </button>

                    ))

                }

            </div>

        </div>

    );

}

export default FavoriteCities;