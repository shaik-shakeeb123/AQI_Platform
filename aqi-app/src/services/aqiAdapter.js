export const adaptCurrentAQI = (res) => {
    if (!res) return null;
    return {
        status: "ok",
        data: {
            aqi: res.aqi,
            city: {
                name: res.city,
                geo: [res.latitude || 0, res.longitude || 0]
            },
            dominentpol: res.dominant_pollutant,
            iaqi: {
                pm25: res.pm25 !== null && res.pm25 !== undefined ? { v: res.pm25 } : undefined,
                pm10: res.pm10 !== null && res.pm10 !== undefined ? { v: res.pm10 } : undefined,
                co: res.co !== null && res.co !== undefined ? { v: res.co } : undefined,
                no2: res.no2 !== null && res.no2 !== undefined ? { v: res.no2 } : undefined,
                so2: res.so2 !== null && res.so2 !== undefined ? { v: res.so2 } : undefined,
                o3: res.o3 !== null && res.o3 !== undefined ? { v: res.o3 } : undefined,
                t: res.temperature !== null && res.temperature !== undefined ? { v: res.temperature } : undefined,
                h: res.humidity !== null && res.humidity !== undefined ? { v: res.humidity } : undefined,
                w: res.wind_speed !== null && res.wind_speed !== undefined ? { v: res.wind_speed } : undefined,
                p: res.pressure !== null && res.pressure !== undefined ? { v: res.pressure } : undefined
            },
            time: {
                s: res.recorded_at
            }
        }
    };
};
