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

const KMH_TO_MS = 3.6;

export const adaptWeather = (res) => {
    if (!res) return null;

    return {
        cod: 200,
        name: res.city,
        sys: {
            country: res.country_code || null,
            sunrise: res.sunrise_timestamp ?? null,
            sunset: res.sunset_timestamp ?? null
        },
        weather: [
            {
                main: res.condition || null,
                description: res.condition_description || null,
                icon: res.condition_icon || null
            }
        ],
        main: {
            temp: res.temperature ?? null,
            feels_like: res.feels_like ?? null,
            humidity: res.humidity ?? null
        },
        wind: {
            speed: res.wind_speed != null ? Number((res.wind_speed / KMH_TO_MS).toFixed(2)) : null,
            deg: res.wind_direction ?? null
        }
    };
};
