import React, { useState, useEffect } from "react";

function CountdownTimer({ initialSeconds = 180 }) {
    const [refreshIn, setRefreshIn] = useState(initialSeconds);

    useEffect(() => {
        const timer = setInterval(() => {
            setRefreshIn((prev) => {
                if (prev <= 1) {
                    return initialSeconds;
                }
                return prev - 1;
            });
        }, 1000);

        return () => clearInterval(timer);
    }, [initialSeconds]);

    return (
        <div>
            <small>Refresh</small>
            <h4>
                {Math.floor(refreshIn / 60)}:
                {String(refreshIn % 60).padStart(2, "0")}
            </h4>
        </div>
    );
}

export default CountdownTimer;
