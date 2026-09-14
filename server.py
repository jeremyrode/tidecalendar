"""
server.py - Lightweight HTTP Server for reTerminal E1004 Tide Calendar.
- Serves 1600x1200 PNG images for the Seeed reTerminal E1004 running epd-photoframe.
- Injects HTTP 'Refresh:' header so the ESP32 knows how long to deep-sleep.
- Captures battery, voltage, temperature, and humidity telemetry from query parameters.
- Serves interactive live HTML preview for web browsers at http://<pi-ip>:8080/
- Auto-caches rendered image so ESP32 downloads instantly (<50ms) without waiting.
"""

import os
import sys
import time
import datetime
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import threading
from typing import Dict, Any, Optional

import yaml
from renderer import TideCalendarRenderer, load_config
from fetcher import TideDataFetcher

# Global state for server
SERVER_STATE = {
    "last_render_time": 0.0,
    "last_telemetry": {},
    "telemetry_history": [],
    "rendering_lock": threading.Lock()
}

class TideServerHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        # Clean formatted console log
        print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {self.address_string()} - {format % args}")

    def _get_refresh_seconds(self) -> int:
        """Calculate sleep duration for E1004 based on config or schedule."""
        config = load_config()
        refresh_mode = config.get("server", {}).get("schedule_mode", "interval")
        
        if refresh_mode == "daily":
            # Sleep until target daily hour (e.g. 4:00 AM)
            target_hour = config.get("server", {}).get("daily_refresh_hour", 4)
            now = datetime.datetime.now()
            target = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
            if now >= target:
                target += datetime.timedelta(days=1)
            sleep_sec = int((target - now).total_seconds())
            return max(3600, sleep_sec)
        else:
            # Fixed interval in seconds (default 4 hours / 14400s)
            return config.get("server", {}).get("refresh_interval_seconds", 14400)

    def _ensure_fresh_image(self, force: bool = False, max_age_seconds: int = 1800) -> Dict[str, str]:
        """Ensure rendered image exists and is fresh (within max_age_seconds)."""
        now = time.time()
        with SERVER_STATE["rendering_lock"]:
            rgb_path = os.path.abspath(os.path.join("output", "tide_calendar_1600x1200.png"))
            spectra6_path = os.path.abspath(os.path.join("output", "tide_calendar_spectra6.png"))
            html_path = os.path.abspath(os.path.join("output", "tide_calendar.html"))

            is_fresh = (
                not force
                and os.path.exists(spectra6_path)
                and (now - SERVER_STATE["last_render_time"]) < max_age_seconds
            )

            if not is_fresh:
                print("[Server] Generating fresh tide calendar image...")
                renderer = TideCalendarRenderer()
                res = renderer.render_image()
                SERVER_STATE["last_render_time"] = time.time()
                return res

            return {
                "html": html_path,
                "rgb_png": rgb_path,
                "spectra6_png": spectra6_path
            }

    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query = urllib.parse.parse_qs(parsed_url.query)

        # Telemetry logging from epd-photoframe
        if query:
            telemetry = {k: v[0] for k, v in query.items()}
            telemetry["timestamp"] = datetime.datetime.now().isoformat()
            telemetry["client_ip"] = self.client_address[0]
            SERVER_STATE["last_telemetry"] = telemetry
            SERVER_STATE["telemetry_history"].append(telemetry)
            if len(SERVER_STATE["telemetry_history"]) > 100:
                SERVER_STATE["telemetry_history"].pop(0)

            print(f"[Device Telemetry] Battery: {telemetry.get('battery', 'N/A')}% "
                  f"({telemetry.get('voltage', 'N/A')}V) | "
                  f"Temp: {telemetry.get('temp', 'N/A')}C | "
                  f"Humidity: {telemetry.get('humidity', 'N/A')}%")

        # 1. Main image endpoints for reTerminal E1004 (epd-photoframe)
        if path in ["/screen/encinitas-tide", "/screen/tide.png", "/screen", "/tide.png"]:
            config = load_config()
            palette_mode = config.get("display", {}).get("palette_mode", "spectra6")
            res = self._ensure_fresh_image()

            img_path = res["spectra6_png"] if palette_mode == "spectra6" else res["rgb_png"]
            if not os.path.exists(img_path):
                self.send_error(500, "Image file not found")
                return

            with open(img_path, "rb") as f:
                img_data = f.read()

            refresh_sec = self._get_refresh_seconds()

            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(img_data)))
            # The critical header for epd-photoframe sleep management:
            self.send_header("Refresh", f"{refresh_sec}; url={path}")
            self.send_header("X-Epd-Next-Refresh-Sec", str(refresh_sec))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(img_data)
            return

        # 2. Raw 24-bit RGB image endpoint
        if path in ["/screen/raw.png", "/tide_rgb.png"]:
            res = self._ensure_fresh_image()
            img_path = res["rgb_png"]
            if not os.path.exists(img_path):
                self.send_error(500, "RGB image not found")
                return
            with open(img_path, "rb") as f:
                img_data = f.read()
            refresh_sec = self._get_refresh_seconds()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(img_data)))
            self.send_header("Refresh", str(refresh_sec))
            self.send_header("X-Epd-Next-Refresh-Sec", str(refresh_sec))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(img_data)
            return

        # 3. Direct HTML preview in browser
        if path in ["/", "/preview", "/index.html"]:
            res = self._ensure_fresh_image()
            html_path = res["html"]
            if not os.path.exists(html_path):
                self.send_error(500, "HTML preview not found")
                return
            with open(html_path, "rb") as f:
                html_data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html_data)))
            self.end_headers()
            self.wfile.write(html_data)
            return

        # 4. CSS file
        if path in ["/style.css", "/templates/style.css"]:
            css_path = os.path.join("templates", "style.css")
            if not os.path.exists(css_path):
                self.send_error(404, "style.css not found")
                return
            with open(css_path, "rb") as f:
                css_data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/css; charset=utf-8")
            self.send_header("Content-Length", str(len(css_data)))
            self.end_headers()
            self.wfile.write(css_data)
            return

        # 5. Force refresh endpoint
        if path == "/refresh":
            print("[Server] Manual refresh triggered via HTTP /refresh")
            res = self._ensure_fresh_image(force=True)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = {
                "status": "success",
                "message": "Rendered fresh tide calendar",
                "render_time": datetime.datetime.fromtimestamp(SERVER_STATE["last_render_time"]).isoformat(),
                "files": res
            }
            self.wfile.write(json.dumps(resp, indent=2).encode("utf-8"))
            return

        # 6. Status and telemetry API
        if path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            config = load_config()
            status_data = {
                "service": "Encinitas Tide Calendar Server",
                "target_device": "Seeed reTerminal E1004 (13.3-inch Spectra 6)",
                "station_id": config["noaa"]["station_id"],
                "last_render": datetime.datetime.fromtimestamp(SERVER_STATE["last_render_time"]).isoformat() if SERVER_STATE["last_render_time"] else None,
                "refresh_interval_sec": self._get_refresh_seconds(),
                "last_device_telemetry": SERVER_STATE["last_telemetry"]
            }
            self.wfile.write(json.dumps(status_data, indent=2).encode("utf-8"))
            return

        self.send_error(404, "Endpoint not found")

def run_server() -> None:
    config = load_config()
    host = config["server"]["host"]
    port = config["server"]["port"]

    # Initial pre-render so server is immediately ready
    print("=" * 60)
    print("ENCINITAS TIDE CALENDAR SERVER (reTerminal E1004)")
    print("=" * 60)
    print(f"Server starting on http://{host}:{port}/")
    print(f"Device endpoint: http://{host}:{port}/screen/encinitas-tide")
    print(f"Browser preview: http://{host}:{port}/preview")

    # Initial background render
    try:
        renderer = TideCalendarRenderer()
        renderer.render_image()
        SERVER_STATE["last_render_time"] = time.time()
        print("[Server] Initial image generation complete.")
    except Exception as e:
        print(f"[Warning] Initial render failed: {e}. Will retry on request.")

    server = HTTPServer((host, port), TideServerHandler)
    print(f"[Server] Ready and listening on {host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Server] Shutting down.")
        server.server_close()

if __name__ == "__main__":
    run_server()
