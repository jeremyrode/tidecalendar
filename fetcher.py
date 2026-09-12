"""
fetcher.py - NOAA Tides and Currents Data Fetcher & Processor for Encinitas, CA.
Fetches 6-minute harmonic predictions and High/Low extrema for station 9410230 (La Jolla / Scripps Pier).
Caches data locally to prevent rate limits and support offline resilience.
"""

import os
import json
import time
import datetime
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional
import yaml
import astronomy

# Load configuration
def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

class TideDataFetcher:
    def __init__(self, config_path: str = "config.yaml"):
        self.config = load_config(config_path)
        self.station_id = self.config["noaa"]["station_id"]
        self.datum = self.config["noaa"]["datum"]
        self.units = self.config["noaa"]["units"]
        self.timezone = self.config["noaa"]["time_zone"]
        self.cache_dir = self.config["cache"]["cache_dir"]
        self.cache_ttl = self.config["cache"]["cache_ttl_hours"] * 3600
        os.makedirs(self.cache_dir, exist_ok=True)

    def _get_cache_path(self, key: str, date_str: str) -> str:
        return os.path.join(self.cache_dir, f"{key}_{self.station_id}_{date_str}.json")

    def _fetch_noaa_api(self, params: Dict[str, str], cache_key: str, date_str: str) -> Optional[Dict[str, Any]]:
        """Fetch from NOAA CO-OPS API with disk caching."""
        cache_path = self._get_cache_path(cache_key, date_str)

        # Check valid cache
        if os.path.exists(cache_path):
            file_age = time.time() - os.path.getmtime(cache_path)
            if file_age < self.cache_ttl:
                try:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    pass

        query_str = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?{query_str}"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "EncinitasTideCalendar/1.0"})
            with urllib.request.urlopen(req, timeout=12) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    if "error" in data:
                        print(f"[Warning] NOAA API error: {data['error']}")
                        # Fallback to expired cache if available
                        if os.path.exists(cache_path):
                            with open(cache_path, "r", encoding="utf-8") as f:
                                return json.load(f)
                        return None
                    with open(cache_path, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
                    return data
        except Exception as e:
            print(f"[Error] Failed to fetch NOAA API ({url}): {e}")
            # Fallback to expired cache
            if os.path.exists(cache_path):
                print(f"[Info] Using cached data from {cache_path}")
                try:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    pass
            return None

    def get_day_predictions(self, date: datetime.date) -> List[Dict[str, Any]]:
        """Fetch 6-minute predictions for a 24-hour day."""
        date_str = date.strftime("%Y%m%d")
        params = {
            "begin_date": date_str,
            "end_date": date_str,
            "station": self.station_id,
            "product": "predictions",
            "datum": self.datum,
            "time_zone": self.timezone,
            "interval": "6",
            "units": self.units,
            "format": "json"
        }
        res = self._fetch_noaa_api(params, "pred_6min", date_str)
        if res and "predictions" in res:
            return res["predictions"]
        return []

    def get_multiday_extrema(self, start_date: datetime.date, days: int = 6) -> List[Dict[str, Any]]:
        """Fetch High/Low extrema for multiple days."""
        start_str = start_date.strftime("%Y%m%d")
        end_date = start_date + datetime.timedelta(days=days)
        end_str = end_date.strftime("%Y%m%d")
        params = {
            "begin_date": start_str,
            "end_date": end_str,
            "station": self.station_id,
            "product": "predictions",
            "datum": self.datum,
            "time_zone": self.timezone,
            "interval": "hilo",
            "units": self.units,
            "format": "json"
        }
        res = self._fetch_noaa_api(params, f"hilo_{days}d", start_str)
        if res and "predictions" in res:
            return res["predictions"]
        return []

    def get_complete_tide_data(self, target_date: Optional[datetime.date] = None) -> Dict[str, Any]:
        """
        Assemble the complete data payload for the tide calendar:
        - Today's date, day, month
        - Solar times (sunrise, sunset, dusk, dawn)
        - Lunar phase (illumination, phase name, SVG moon)
        - Today's 6-minute curve points
        - Today's High and Low extrema
        - Current water level, rate of change, next tide event
        - 5-day outlook
        """
        if target_date is None:
            now = datetime.datetime.now()
            target_date = now.date()
        else:
            now = datetime.datetime.combine(target_date, datetime.datetime.now().time())

        lat = self.config["location"]["latitude"]
        lon = self.config["location"]["longitude"]

        # Solar & Lunar calculations
        solar = astronomy.get_solar_times(lat, lon, target_date)
        moon = astronomy.get_moon_phase(target_date)

        # 6-minute predictions for today
        raw_predictions = self.get_day_predictions(target_date)

        # High/Low extrema for today + 5 days
        raw_extrema = self.get_multiday_extrema(target_date, days=6)

        # Process 6-min curve
        curve_points = []
        min_height = 999.0
        max_height = -999.0

        for pt in raw_predictions:
            # pt['t'] format: "2026-09-12 14:24"
            dt_pt = datetime.datetime.strptime(pt["t"], "%Y-%m-%d %H:%M")
            h = float(pt["v"])
            fractional_hour = dt_pt.hour + (dt_pt.minute / 60.0)
            curve_points.append({
                "time_str": dt_pt.strftime("%I:%M %p").lstrip("0"),
                "hour": fractional_hour,
                "height": h
            })
            if h < min_height: min_height = h
            if h > max_height: max_height = h

        # Fallback if no data retrieved
        if not curve_points:
            min_height, max_height = 0.0, 6.0

        # Group extrema by date
        extrema_by_date: Dict[str, List[Dict[str, Any]]] = {}
        for ext in raw_extrema:
            dt_ext = datetime.datetime.strptime(ext["t"], "%Y-%m-%d %H:%M")
            d_key = dt_ext.date().strftime("%Y-%m-%d")
            h = float(ext["v"])
            is_high = (ext["type"].upper() == "H")
            entry = {
                "datetime": dt_ext,
                "time_str": dt_ext.strftime("%I:%M %p").lstrip("0"),
                "hour": dt_ext.hour + (dt_ext.minute / 60.0),
                "height": h,
                "height_str": f"{h:+.1f} ft" if h >= 0 else f"{h:.1f} ft",
                "type": "High" if is_high else "Low",
                "is_high": is_high
            }
            extrema_by_date.setdefault(d_key, []).append(entry)

        today_key = target_date.strftime("%Y-%m-%d")
        today_extrema = extrema_by_date.get(today_key, [])

        # Current water level estimation & trend
        current_hour = now.hour + (now.minute / 60.0)
        current_water_level = None
        current_trend = "Ebbing"
        rate_of_change = 0.0
        next_event = None

        if curve_points:
            # Find closest points for interpolation
            closest_idx = 0
            closest_diff = 999.0
            for i, p in enumerate(curve_points):
                diff = abs(p["hour"] - current_hour)
                if diff < closest_diff:
                    closest_diff = diff
                    closest_idx = i

            current_water_level = curve_points[closest_idx]["height"]

            # Compute trend and rate of change (over 30 min)
            prev_idx = max(0, closest_idx - 5)
            next_idx = min(len(curve_points) - 1, closest_idx + 5)
            dt_hours = curve_points[next_idx]["hour"] - curve_points[prev_idx]["hour"]
            if dt_hours > 0:
                dh = curve_points[next_idx]["height"] - curve_points[prev_idx]["height"]
                rate_of_change = dh / dt_hours
                current_trend = "Rising (Flooding)" if rate_of_change > 0.05 else ("Falling (Ebbing)" if rate_of_change < -0.05 else "Slack Water")

        # Find next upcoming extremum
        for ext in today_extrema:
            if ext["datetime"] > now:
                time_diff = ext["datetime"] - now
                diff_hours = int(time_diff.total_seconds() // 3600)
                diff_mins = int((time_diff.total_seconds() % 3600) // 60)
                in_str = f"in {diff_hours}h {diff_mins:02d}m" if diff_hours > 0 else f"in {diff_mins}m"
                next_event = {
                    "type": ext["type"],
                    "height_str": ext["height_str"],
                    "time_str": ext["time_str"],
                    "in_str": in_str
                }
                break

        # If next event is tomorrow
        if not next_event:
            tomorrow_key = (target_date + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
            tomorrow_extrema = extrema_by_date.get(tomorrow_key, [])
            if tomorrow_extrema:
                ext = tomorrow_extrema[0]
                time_diff = ext["datetime"] - now
                diff_hours = int(time_diff.total_seconds() // 3600)
                diff_mins = int((time_diff.total_seconds() % 3600) // 60)
                next_event = {
                    "type": ext["type"],
                    "height_str": ext["height_str"],
                    "time_str": ext["time_str"],
                    "in_str": f"tomorrow at {ext['time_str']}"
                }

        # Multi-day outlook (next 5 days)
        outlook = []
        for d_offset in range(1, 6):
            f_date = target_date + datetime.timedelta(days=d_offset)
            f_key = f_date.strftime("%Y-%m-%d")
            f_ext = extrema_by_date.get(f_key, [])
            f_moon = astronomy.get_moon_phase(f_date)
            outlook.append({
                "day_name": f_date.strftime("%a"),
                "date_str": f_date.strftime("%b %d"),
                "extrema": f_ext,
                "moon_svg": f_moon["svg_markup"],
                "moon_phase": f_moon["phase_name"]
            })

        # Calculate daily tidal range
        today_range = (max_height - min_height) if max_height > min_height else 0.0

        return {
            "location_name": self.config["location"]["name"],
            "sub_name": self.config["location"]["sub_name"],
            "station_id": self.station_id,
            "station_name": self.config["noaa"]["station_name"],
            "datum": self.datum,
            "units": self.units,
            "today_date": target_date.strftime("%A, %B %d, %Y"),
            "today_short_date": target_date.strftime("%b %d, %Y"),
            "now_time_str": now.strftime("%I:%M %p").lstrip("0"),
            "solar": solar,
            "moon": moon,
            "curve_points": curve_points,
            "today_extrema": today_extrema,
            "min_height": min_height,
            "max_height": max_height,
            "today_range_str": f"{today_range:.1f} ft",
            "current_water_level": current_water_level,
            "current_water_level_str": f"{current_water_level:+.1f} ft" if current_water_level is not None else "--",
            "current_trend": current_trend,
            "rate_of_change_str": f"{rate_of_change:+.1f} ft/hr",
            "next_event": next_event,
            "outlook": outlook,
            "current_hour": current_hour
        }

if __name__ == "__main__":
    fetcher = TideDataFetcher()
    data = fetcher.get_complete_tide_data()
    print("--- Tide Data Summary ---")
    print(f"Location: {data['location_name']}")
    print(f"Date: {data['today_date']}")
    print(f"Current Level: {data['current_water_level_str']} ({data['current_trend']})")
    print(f"Next Event: {data['next_event']}")
    print(f"Today's Extrema: {[(e['type'], e['time_str'], e['height_str']) for e in data['today_extrema']]}")
    print(f"Solar: Dawn {data['solar']['dawn_str']}, Sunrise {data['solar']['sunrise_str']}, Sunset {data['solar']['sunset_str']}")
    print(f"Moon: {data['moon']['phase_name']} ({data['moon']['illumination_pct']}%)")
    print(f"5-Day Outlook entries: {len(data['outlook'])}")
