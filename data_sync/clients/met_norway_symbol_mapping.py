from __future__ import annotations

from typing import Tuple

# Mapping of base symbol codes to (condition, description, base_icon, wmo_code)
# Suffixes (_day, _night, _polartwilight) are handled dynamically for icon daylight.
_SYMBOL_MAP: dict[str, tuple[str, str, str, int]] = {
    "clearsky": ("Clear", "Clear sky", "01", 0),
    "fair": ("Clear", "Mainly clear", "02", 1),
    "partlycloudy": ("Clouds", "Partly cloudy", "03", 2),
    "cloudy": ("Clouds", "Overcast", "04", 3),
    "rainshowers": ("Rain", "Rain showers", "09", 80),
    "rainshowersandthunder": ("Thunderstorm", "Rain showers with thunder", "11", 95),
    "sleetshowers": ("Sleet", "Sleet showers", "13", 83),
    "snowshowers": ("Snow", "Snow showers", "13", 85),
    "rain": ("Rain", "Rain", "10", 61),
    "heavyrain": ("Rain", "Heavy rain", "10", 65),
    "heavyrainandthunder": ("Thunderstorm", "Heavy rain and thunder", "11", 96),
    "sleet": ("Sleet", "Sleet", "13", 68),
    "snow": ("Snow", "Snow", "13", 71),
    "snowandthunder": ("Thunderstorm", "Snow and thunder", "11", 95),
    "fog": ("Fog", "Fog", "50", 45),
    "sleetshowersandthunder": ("Thunderstorm", "Sleet showers and thunder", "11", 95),
    "snowshowersandthunder": ("Thunderstorm", "Snow showers and thunder", "11", 95),
    "rainandthunder": ("Thunderstorm", "Rain and thunder", "11", 95),
    "sleetandthunder": ("Thunderstorm", "Sleet and thunder", "11", 95),
    "lightrainshowersandthunder": ("Thunderstorm", "Light rain showers and thunder", "11", 95),
    "heavyrainshowersandthunder": ("Thunderstorm", "Heavy rain showers and thunder", "11", 96),
    "lightssleetshowersandthunder": ("Thunderstorm", "Light sleet showers and thunder", "11", 95),
    "heavysleetshowersandthunder": ("Thunderstorm", "Heavy sleet showers and thunder", "11", 96),
    "lightssnowshowersandthunder": ("Thunderstorm", "Light snow showers and thunder", "11", 95),
    "heavysnowshowersandthunder": ("Thunderstorm", "Heavy snow showers and thunder", "11", 96),
    "lightrainandthunder": ("Thunderstorm", "Light rain and thunder", "11", 95),
    "lightsleetandthunder": ("Thunderstorm", "Light sleet and thunder", "11", 95),
    "heavysleetandthunder": ("Thunderstorm", "Heavy sleet and thunder", "11", 96),
    "lightsnowandthunder": ("Thunderstorm", "Light snow and thunder", "11", 95),
    "heavysnowandthunder": ("Thunderstorm", "Heavy snow and thunder", "11", 96),
    "lightrainshowers": ("Rain", "Light rain showers", "09", 80),
    "heavyrainshowers": ("Rain", "Heavy rain showers", "09", 82),
    "lightsleetshowers": ("Sleet", "Light sleet showers", "13", 83),
    "heavysleetshowers": ("Sleet", "Heavy sleet showers", "13", 84),
    "lightsnowshowers": ("Snow", "Light snow showers", "13", 85),
    "heavysnowshowers": ("Snow", "Heavy snow showers", "13", 86),
    "lightrain": ("Rain", "Light rain", "10", 61),
    "lightsleet": ("Sleet", "Light sleet", "13", 68),
    "heavysleet": ("Sleet", "Heavy sleet", "13", 69),
    "lightsnow": ("Snow", "Light snow", "13", 71),
    "heavysnow": ("Snow", "Heavy snow", "13", 75),
}


def decode_met_norway_symbol(
    symbol_code: str | None,
    is_daytime: bool = True
) -> tuple[str, str, str, int]:
    """Decode a MET Norway symbol_code string into normalized weather condition tuple.
    
    Returns:
        (condition, description, icon_code, wmo_weather_code)
    """
    if not symbol_code:
        return ("Clear", "Clear sky", "01d" if is_daytime else "01n", 0)

    code_lower = str(symbol_code).strip().lower()

    # Determine day/night flag from suffix or is_daytime parameter
    if code_lower.endswith("_night") or code_lower.endswith("_polartwilight"):
        time_suffix = "n"
        base_code = code_lower.replace("_night", "").replace("_polartwilight", "")
    elif code_lower.endswith("_day"):
        time_suffix = "d"
        base_code = code_lower.replace("_day", "")
    else:
        time_suffix = "d" if is_daytime else "n"
        base_code = code_lower

    if base_code in _SYMBOL_MAP:
        cond, desc, base_icon, wmo = _SYMBOL_MAP[base_code]
        # Fog, sleet, snow, thunderstorm use standard icon regardless of suffix in OpenWeatherMap
        if base_icon in ("04", "11", "13", "50"):
            icon = f"{base_icon}d"
        else:
            icon = f"{base_icon}{time_suffix}"
        return (cond, desc, icon, wmo)

    # Fallback for unknown symbols
    return ("Clouds", base_code.replace("_", " ").capitalize(), f"03{time_suffix}", 2)
