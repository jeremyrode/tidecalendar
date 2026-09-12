"""
astronomy.py - Astronomical calculations for Sun and Moon in Encinitas, CA.
Calculates sunrise, sunset, twilight, daylight duration, and lunar phases.
Pure Python, zero external binary dependencies.
"""

import math
import datetime
from typing import Dict, Any, Tuple

def get_solar_times(lat: float, lon: float, date: datetime.date) -> Dict[str, Any]:
    """
    Calculate sunrise, sunset, dawn (civil twilight begin), and dusk (civil twilight end)
    using the NOAA solar position formulation.
    Returns times as datetime.time objects and formatted strings.
    """
    # Day of year
    day_of_year = date.timetuple().tm_yday

    # Fractional year in radians
    gamma = 2 * math.pi / 365 * (day_of_year - 1)

    # Equation of time in minutes
    eqtime = 229.18 * (
        0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma)
    )

    # Solar declination angle in radians
    decl = (
        0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma)
    )

    lat_rad = math.radians(lat)

    def calc_hour_angle(zenith_deg: float) -> float:
        zenith_rad = math.radians(zenith_deg)
        cos_ha = (math.cos(zenith_rad) / (math.cos(lat_rad) * math.cos(decl))) - (math.tan(lat_rad) * math.tan(decl))
        cos_ha = max(-1.0, min(1.0, cos_ha))
        return math.degrees(math.acos(cos_ha))

    # Standard sunrise/sunset zenith is 90.833 degrees (accounting for atmospheric refraction & solar disc)
    ha_sun = calc_hour_angle(90.833)
    # Civil twilight zenith is 96.0 degrees (-6 deg elevation)
    ha_twilight = calc_hour_angle(96.0)

    # Determine local UTC offset (DST aware for US/Pacific)
    # California is UTC-7 during PDT (approx second Sun of Mar to first Sun of Nov), UTC-8 during PST
    # We can infer timezone offset from datetime.now() with local timezone
    tz_offset = -7.0 if is_dst(date) else -8.0

    # Solar noon in local minutes from midnight
    solar_noon_utc_min = 720 - 4 * lon - eqtime
    solar_noon_local_min = solar_noon_utc_min + (tz_offset * 60)

    sunrise_min = solar_noon_local_min - (ha_sun * 4)
    sunset_min = solar_noon_local_min + (ha_sun * 4)
    dawn_min = solar_noon_local_min - (ha_twilight * 4)
    dusk_min = solar_noon_local_min + (ha_twilight * 4)

    def min_to_time(m: float) -> Tuple[datetime.time, str]:
        m = m % 1440
        hour = int(m // 60)
        minute = int(m % 60)
        t = datetime.time(hour, minute)
        # Format as 12-hour AM/PM string e.g. "6:32 AM"
        formatted = t.strftime("%I:%M %p").lstrip("0")
        return t, formatted

    sunrise_time, sunrise_str = min_to_time(sunrise_min)
    sunset_time, sunset_str = min_to_time(sunset_min)
    dawn_time, dawn_str = min_to_time(dawn_min)
    dusk_time, dusk_str = min_to_time(dusk_min)

    daylight_mins = int(sunset_min - sunrise_min)
    daylight_hrs = daylight_mins // 60
    daylight_rem_mins = daylight_mins % 60
    daylight_str = f"{daylight_hrs}h {daylight_rem_mins:02d}m"

    return {
        "sunrise_time": sunrise_time,
        "sunrise_str": sunrise_str,
        "sunset_time": sunset_time,
        "sunset_str": sunset_str,
        "dawn_str": dawn_str,
        "dusk_str": dusk_str,
        "sunrise_min": sunrise_min,
        "sunset_min": sunset_min,
        "daylight_str": daylight_str,
        "daylight_fraction_of_day": daylight_mins / 1440.0
    }

def is_dst(date: datetime.date) -> bool:
    """Check if date is in US Daylight Saving Time (second Sunday of March to first Sunday of November)."""
    year = date.year
    # Second Sunday in March
    mar1 = datetime.date(year, 3, 1)
    mar_second_sun = 1 + (6 - mar1.weekday()) % 7 + 7
    dst_start = datetime.date(year, 3, mar_second_sun)

    # First Sunday in November
    nov1 = datetime.date(year, 11, 1)
    nov_first_sun = 1 + (6 - nov1.weekday()) % 7
    dst_end = datetime.date(year, 11, nov_first_sun)

    return dst_start <= date < dst_end

def get_moon_phase(date: datetime.date) -> Dict[str, Any]:
    """
    Calculate lunar phase, illumination percentage, phase name, and SVG drawing parameters.
    Based on the standard astronomical synodic month formula (~29.53058867 days).
    Reference known New Moon: Jan 11, 2024, 11:57 UTC (Julian Day 2460320.998)
    """
    dt = datetime.datetime(date.year, date.month, date.day, 12, 0)
    # Julian Date
    a = (14 - dt.month) // 12
    y = dt.year + 4800 - a
    m = dt.month + 12 * a - 3
    jd = dt.day + ((153 * m + 2) // 5) + 365 * y + y // 4 - y // 100 + y // 400 - 32045 + (dt.hour - 12) / 24.0

    synodic_month = 29.53058867
    ref_new_moon_jd = 2451549.5  # Jan 6, 2000, 18:14 UTC

    phase_days = (jd - ref_new_moon_jd) % synodic_month
    phase_ratio = phase_days / synodic_month  # 0.0 (New) to 0.5 (Full) to 1.0 (New)

    # Illumination fraction (0.0 to 1.0)
    illumination = (1 - math.cos(2 * math.pi * phase_ratio)) / 2.0
    illum_pct = round(illumination * 100)

    # Phase classification & name
    if phase_ratio < 0.03 or phase_ratio >= 0.97:
        phase_name = "New Moon"
        tide_type = "Spring Tide (Higher Highs & Lower Lows)"
    elif phase_ratio < 0.22:
        phase_name = "Waxing Crescent"
        tide_type = "Moderate Tide"
    elif phase_ratio < 0.28:
        phase_name = "First Quarter"
        tide_type = "Neap Tide (Smaller Tidal Range)"
    elif phase_ratio < 0.47:
        phase_name = "Waxing Gibbous"
        tide_type = "Building Spring Tide"
    elif phase_ratio < 0.53:
        phase_name = "Full Moon"
        tide_type = "Spring Tide (Max Tidal Range)"
    elif phase_ratio < 0.72:
        phase_name = "Waning Gibbous"
        tide_type = "Building Neap Tide"
    elif phase_ratio < 0.78:
        phase_name = "Last Quarter"
        tide_type = "Neap Tide (Smaller Tidal Range)"
    else:
        phase_name = "Waning Crescent"
        tide_type = "Moderate Tide"

    # SVG Moon disc rendering parameters (radius R=36)
    # We will generate clean SVG markup for the moon
    svg_markup = generate_moon_svg(phase_ratio, radius=32)

    return {
        "phase_ratio": round(phase_ratio, 3),
        "age_days": round(phase_days, 1),
        "illumination_pct": illum_pct,
        "phase_name": phase_name,
        "tide_type": tide_type,
        "svg_markup": svg_markup
    }

def generate_moon_svg(phase_ratio: float, radius: int = 32) -> str:
    """
    Generate an SVG snippet showing the lunar illumination disk.
    Radius = R. Center at (R, R).
    """
    r = radius
    d = 2 * r
    # Outer dark disk representing unlit portion
    # Lighted part geometry
    is_waxing = phase_ratio < 0.5
    # Normalized position between new (0), full (1), new (0)
    x = math.cos(2 * math.pi * phase_ratio)
    # rx is the semi-major horizontal axis of the terminator ellipse
    rx = abs(x) * r

    dark_color = "#2a3441"
    light_color = "#f6d32d"  # Spectra 6 Yellow for moon light!

    if phase_ratio < 0.02 or phase_ratio > 0.98:
        # New Moon: All dark
        return f'<svg width="{d}" height="{d}" viewBox="0 0 {d} {d}"><circle cx="{r}" cy="{r}" r="{r}" fill="{dark_color}" stroke="#627284" stroke-width="1.5"/></svg>'
    elif 0.48 <= phase_ratio <= 0.52:
        # Full Moon: All light
        return f'<svg width="{d}" height="{d}" viewBox="0 0 {d} {d}"><circle cx="{r}" cy="{r}" r="{r}" fill="{light_color}" stroke="#627284" stroke-width="1.5"/></svg>'

    if is_waxing:
        # Waxing: Right side is illuminated
        if phase_ratio < 0.25:
            # Crescent: Right half circle minus terminator
            # Arc from top to bottom on right, then ellipse back
            path = f"M {r} 0 A {r} {r} 0 0 1 {r} {d} A {rx} {r} 0 0 1 {r} 0 Z"
        else:
            # Gibbous: Right half circle plus terminator
            path = f"M {r} 0 A {r} {r} 0 0 1 {r} {d} A {rx} {r} 0 0 0 {r} 0 Z"
    else:
        # Waning: Left side is illuminated
        if phase_ratio < 0.75:
            # Gibbous: Left half circle plus terminator
            path = f"M {r} 0 A {r} {r} 0 0 0 {r} {d} A {rx} {r} 0 0 1 {r} 0 Z"
        else:
            # Crescent: Left half circle minus terminator
            path = f"M {r} 0 A {r} {r} 0 0 0 {r} {d} A {rx} {r} 0 0 0 {r} 0 Z"

    return f'''<svg width="{d}" height="{d}" viewBox="0 0 {d} {d}">
      <circle cx="{r}" cy="{r}" r="{r}" fill="{dark_color}" stroke="#627284" stroke-width="1.5"/>
      <path d="{path}" fill="{light_color}"/>
    </svg>'''
