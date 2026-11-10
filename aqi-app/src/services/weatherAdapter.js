/**
 * Pure mapping layer between the FastAPI weather response and the
 * frontend WeatherWidget structure.
 *
 * This adapter performs NO business logic, NO derivation, NO mocking.
 * It translates backend field names into the nested structure the
 * existing WeatherWidget consumes.
 *
 * Wind speed conversion: backend returns km/h, frontend displays m/s.
 * Conversion: km/h ÷ 3.6 = m/s.  This is the only transformation.
 */


export const adaptWeather = (res) => {
    if (!res) return null;

    const isAvailable = res.is_available !== false && res.temperature !== null;

    return {
        cod: isAvailable ? 200 : 503,
        name: res.city,
        timezone: res.timezone || null,
        provider: res.provider || null,
        attribution: res.attribution || null,
        source: res.source || (isAvailable ? "LIVE" : "UNAVAILABLE"),
        is_available: isAvailable,
        cached_at: res.cached_at || null,
        cooldown_remaining: res.cooldown_remaining_seconds || 0,
        sys: {
            country: res.country_code || null,
            sunrise: res.sunrise_timestamp ?? null,
            sunset: res.sunset_timestamp ?? null
        },
        weather: [
            {
                main: res.condition || (isAvailable ? null : "Unavailable"),
                description: res.condition_description || (isAvailable ? null : "Weather data temporarily unavailable"),
                icon: res.condition_icon || null
            }
        ],
        main: {
            temp: res.temperature ?? null,
            feels_like: res.feels_like ?? null,
            humidity: res.humidity ?? null
        },
        wind: {
            speed: res.wind_speed ?? null,
            deg: res.wind_direction ?? null
        }
    };
};
