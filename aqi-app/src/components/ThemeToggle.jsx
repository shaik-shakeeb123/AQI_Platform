import React from "react";
import "./ThemeToggle.css";

function ThemeToggle({ theme, setTheme }) {

    const isDark = theme === "dark";

    return (

        <button

            className="theme-btn"

            onClick={() =>

                setTheme(

                    isDark

                        ? "light"

                        : "dark"

                )

            }

            title={

                isDark

                    ? "Switch to Light Mode"

                    : "Switch to Dark Mode"

            }

            aria-label="Toggle Theme"

        >

            <span className="theme-icon">

                {isDark ? "☀️" : "🌙"}

            </span>

            <span className="theme-text">

                {

                    isDark

                        ? "Light Mode"

                        : "Dark Mode"

                }

            </span>

        </button>

    );

}

export default ThemeToggle;