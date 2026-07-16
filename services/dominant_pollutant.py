from typing import Optional, Tuple
from services.aqi_category import get_aqi_category

# US EPA Standard Breakpoints: (C_low, C_high, I_low, I_high)
# Units expected by US EPA:
# - PM2.5: µg/m³
# - PM10: µg/m³
# - NO2: ppb
# - SO2: ppb
# - CO: ppm
# - O3: ppm
BREAKPOINTS = {
    "pm25": [
        (0.0, 12.0, 0.0, 50.0),
        (12.1, 35.4, 51.0, 100.0),
        (35.5, 55.4, 101.0, 150.0),
        (55.5, 150.4, 151.0, 200.0),
        (150.5, 250.4, 201.0, 300.0),
        (250.5, 500.0, 301.0, 500.0)
    ],
    "pm10": [
        (0.0, 54.0, 0.0, 50.0),
        (55.0, 154.0, 51.0, 100.0),
        (155.0, 254.0, 101.0, 150.0),
        (255.0, 354.0, 151.0, 200.0),
        (355.0, 424.0, 201.0, 300.0),
        (425.0, 604.0, 301.0, 500.0)
    ],
    "no2": [
        (0.0, 53.0, 0.0, 50.0),
        (54.0, 100.0, 51.0, 100.0),
        (101.0, 360.0, 101.0, 150.0),
        (361.0, 649.0, 151.0, 200.0),
        (650.0, 1249.0, 201.0, 300.0),
        (1250.0, 2049.0, 301.0, 500.0)
    ],
    "so2": [
        (0.0, 35.0, 0.0, 50.0),
        (36.0, 75.0, 51.0, 100.0),
        (76.0, 185.0, 101.0, 150.0),
        (186.0, 304.0, 151.0, 200.0),
        (305.0, 604.0, 201.0, 300.0),
        (605.0, 1004.0, 301.0, 500.0)
    ],
    "co": [
        (0.0, 4.4, 0.0, 50.0),
        (4.5, 9.4, 51.0, 100.0),
        (9.5, 12.4, 101.0, 150.0),
        (12.5, 15.4, 151.0, 200.0),
        (15.5, 30.4, 201.0, 300.0),
        (30.5, 50.4, 301.0, 500.0)
    ],
    "o3": [
        (0.0, 0.054, 0.0, 50.0),
        (0.055, 0.070, 51.0, 100.0),
        (0.071, 0.085, 101.0, 150.0),
        (0.086, 0.105, 151.0, 200.0),
        (0.106, 0.200, 201.0, 300.0),
        (0.201, 0.600, 301.0, 500.0)
    ]
}

def calculate_sub_index(concentration: Optional[float], pollutant: str) -> Optional[float]:
    """Calculate the sub-index for a pollutant concentration using US EPA breakpoints.

    Converts input values from CPCB database units to US EPA units prior to breakpoint lookup,
    and applies standard US EPA truncating rules.
    """
    if concentration is None or concentration < 0:
        return None
        
    brackets = BREAKPOINTS.get(pollutant.lower())
    if not brackets:
        return None

    # Convert and round/truncate to US EPA specifications
    if pollutant.lower() == "pm25":
        # PM2.5: truncate to 1 decimal place
        concentration = int(concentration * 10) / 10.0
    elif pollutant.lower() == "pm10":
        # PM10: truncate to integer
        concentration = int(concentration)
    elif pollutant.lower() == "co":
        # CO: convert from mg/m3 to ppm, then truncate to 1 decimal place
        ppm_val = concentration / 1.145
        concentration = int(ppm_val * 10) / 10.0
    elif pollutant.lower() == "o3":
        # O3: convert from ug/m3 to ppm, then truncate to 3 decimal places
        ppm_val = (concentration / 1.963) / 1000.0
        concentration = int(ppm_val * 1000) / 1000.0
    elif pollutant.lower() == "no2":
        # NO2: convert from ug/m3 to ppb, then truncate to integer
        ppb_val = concentration / 1.882
        concentration = int(ppb_val)
    elif pollutant.lower() == "so2":
        # SO2: convert from ug/m3 to ppb, then truncate to integer
        ppb_val = concentration / 2.620
        concentration = int(ppb_val)
        
    for c_low, c_high, i_low, i_high in brackets:
        if c_low <= concentration <= c_high:
            # Linear interpolation formula
            return ((i_high - i_low) / (c_high - c_low)) * (concentration - c_low) + i_low
            
    # Cap at 500 if concentration exceeds max bracket
    if concentration > brackets[-1][1]:
        return brackets[-1][3]
        
    return None

def calculate_overall_aqi(
    pm25: Optional[float] = None,
    pm10: Optional[float] = None,
    no2: Optional[float] = None,
    so2: Optional[float] = None,
    co: Optional[float] = None,
    o3: Optional[float] = None
) -> Tuple[Optional[float], Optional[str], Optional[str]]:
    """Calculate the overall US EPA AQI, dominant pollutant, and AQI category."""
    pollutants = {
        "PM2.5": (pm25, "pm25"),
        "PM10": (pm10, "pm10"),
        "NO2": (no2, "no2"),
        "SO2": (so2, "so2"),
        "CO": (co, "co"),
        "O3": (o3, "o3")
    }
    
    max_sub_index = -1.0
    dominant_pollutant = None
    
    for name, (val, key) in pollutants.items():
        sub_index = calculate_sub_index(val, key)
        if sub_index is not None:
            if sub_index > max_sub_index:
                max_sub_index = sub_index
                dominant_pollutant = name
                
    if max_sub_index >= 0:
        category = get_aqi_category(max_sub_index)
        return round(max_sub_index, 2), category, dominant_pollutant
        
    return None, None, None
