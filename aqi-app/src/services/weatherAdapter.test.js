import { adaptWeather, formatWeatherTime } from "./weatherAdapter";

describe("Weather Timezone and Solar Formatting (formatWeatherTime)", () => {
    // Madanapalle test timestamps:
    // UTC: 2026-11-10T00:43:31Z -> Epoch: 1794271411
    // UTC: 2026-11-10T12:16:42Z -> Epoch: 1794313002
    const madanapalleSunriseTs = 1794271411;
    const madanapalleSunsetTs = 1794313002;
    const madanapalleSunriseIso = "2026-11-10T00:43:31+00:00";
    const madanapalleSunsetIso = "2026-11-10T12:16:42+00:00";

    test("Madanapalle: 00:43 UTC displays as 06:13 AM in Asia/Kolkata", () => {
        const formatted = formatWeatherTime(madanapalleSunriseTs, "Asia/Kolkata");
        expect(formatted).toBe("06:13 AM");
    });

    test("Madanapalle: 12:16 UTC displays as 05:46 PM in Asia/Kolkata", () => {
        const formatted = formatWeatherTime(madanapalleSunsetTs, "Asia/Kolkata");
        expect(formatted).toBe("05:46 PM");
    });

    test("Madanapalle: handles ISO 8601 string inputs correctly", () => {
        expect(formatWeatherTime(madanapalleSunriseIso, "Asia/Kolkata")).toBe("06:13 AM");
        expect(formatWeatherTime(madanapalleSunsetIso, "Asia/Kolkata")).toBe("05:46 PM");
    });

    test("Different city timezones: London and New York", () => {
        // 00:43:31 UTC in London (Europe/London, winter GMT = UTC+0)
        expect(formatWeatherTime(madanapalleSunriseTs, "Europe/London")).toBe("12:43 AM");

        // 00:43:31 UTC on Nov 10 in New York (America/New_York, EST = UTC-5) -> 19:43 Nov 9 = 07:43 PM
        expect(formatWeatherTime(madanapalleSunriseTs, "America/New_York")).toBe("07:43 PM");
    });

    test("Daylight-saving transitions (DST) in London and New York", () => {
        // Summer solstice date: July 1 at 04:45 UTC
        const summerUtc = "2026-07-01T04:45:00Z";
        // Winter date: Dec 1 at 07:45 UTC
        const winterUtc = "2026-12-01T07:45:00Z";

        // London: BST (UTC+1) in summer, GMT (UTC+0) in winter
        expect(formatWeatherTime(summerUtc, "Europe/London")).toBe("05:45 AM");
        expect(formatWeatherTime(winterUtc, "Europe/London")).toBe("07:45 AM");

        // New York: EDT (UTC-4) in summer, EST (UTC-5) in winter
        expect(formatWeatherTime(summerUtc, "America/New_York")).toBe("12:45 AM");
        expect(formatWeatherTime(winterUtc, "America/New_York")).toBe("02:45 AM");
    });

    test("Missing or invalid timezone fallback", () => {
        // Missing timezone defaults safely to UTC
        expect(formatWeatherTime(madanapalleSunriseTs, null)).toBe("12:43 AM");
        expect(formatWeatherTime(madanapalleSunriseTs, "")).toBe("12:43 AM");
        expect(formatWeatherTime(madanapalleSunriseTs, undefined)).toBe("12:43 AM");

        // Malformed / non-existent timezone falls back to UTC without throwing
        expect(formatWeatherTime(madanapalleSunriseTs, "Invalid/Non_Existent_Timezone")).toBe("12:43 AM");
    });

    test("Prevents double timezone conversion and handles null timestamps", () => {
        expect(formatWeatherTime(null, "Asia/Kolkata")).toBe("--");
        expect(formatWeatherTime(undefined, "Asia/Kolkata")).toBe("--");
        expect(formatWeatherTime("invalid-date", "Asia/Kolkata")).toBe("--");
    });

    test("adaptWeather maps timezone and solar timestamps cleanly", () => {
        const mockBackendResponse = {
            city: "Madanapalle",
            temperature: 20.3,
            timezone: "Asia/Kolkata",
            sunrise: "2026-11-10T00:43:31+00:00",
            sunset: "2026-11-10T12:16:42+00:00",
            sunrise_timestamp: 1794271411,
            sunset_timestamp: 1794313002,
            provider: "MET Norway",
            attribution: "Data from MET Norway (api.met.no)",
            is_available: true,
            source: "MET_NORWAY",
        };

        const adapted = adaptWeather(mockBackendResponse);
        expect(adapted.timezone).toBe("Asia/Kolkata");
        expect(adapted.sys.sunrise).toBe(1794271411);
        expect(adapted.sys.sunset).toBe(1794313002);

        // Verify end-to-end formatted output matches expected
        expect(formatWeatherTime(adapted.sys.sunrise, adapted.timezone)).toBe("06:13 AM");
        expect(formatWeatherTime(adapted.sys.sunset, adapted.timezone)).toBe("05:46 PM");
    });
});
