"""
renderer.py - Renders the 1600x1200 Tide Calendar for Seeed reTerminal E1004.
- Generates SVG coordinates and curves
- Renders Jinja2 HTML/CSS template
- Captures 1600x1200 PNG using headless Chromium/Chrome/Edge
- Applies Spectra 6 (6-color) Floyd-Steinberg dithering and palette quantization
"""

import os
import sys
import math
import subprocess
import shutil
from typing import Dict, Any, List, Optional
from jinja2 import Environment, FileSystemLoader
from PIL import Image
import yaml
from fetcher import TideDataFetcher

# Load configuration
def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

# Spectra 6 Palette definition
# 6 physical pigment colors: Black, White, Red, Yellow, Blue, Green
SPECTRA6_PALETTE = [
    0, 0, 0,        # 0: Black
    255, 255, 255,  # 1: White
    220, 20, 20,    # 2: Red
    250, 215, 0,    # 3: Yellow
    25, 75, 200,    # 4: Blue
    25, 145, 45     # 5: Green
]
# Pad palette to 256 colors (768 bytes) for PIL 'P' mode
SPECTRA6_PALETTE_256 = SPECTRA6_PALETTE + [0] * (768 - len(SPECTRA6_PALETTE))

def build_svg_chart_data(data: Dict[str, Any], is_clean_graph: bool = True) -> Dict[str, Any]:
    """
    Compute SVG paths, coordinate transformations, gridlines, and pill markers.
    Scales coordinates for either clean_graph (full screen 1600x1100 viewBox) or dashboard mode.
    """
    if is_clean_graph:
        chart_left = 180
        chart_right = 1530
        chart_top = 75
        chart_bottom = 1050
    else:
        chart_left = 78
        chart_right = 1025
        chart_top = 45
        chart_bottom = 430

    chart_width = chart_right - chart_left
    chart_height = chart_bottom - chart_top

    min_val = min(0.0, data["min_height"] - 0.4)
    max_val = max(6.5, data["max_height"] + 0.8)
    val_range = max_val - min_val if max_val > min_val else 6.0

    def to_x(hour: float) -> float:
        return chart_left + (hour / 24.0) * chart_width

    def to_y(val: float) -> float:
        return chart_top + (max_val - val) / val_range * chart_height

    # Convert 6-minute curve points to SVG path
    curve_points = data["curve_points"]
    if curve_points:
        coords = [(to_x(p["hour"]), to_y(p["height"])) for p in curve_points]

        # Line path
        line_path = f"M {coords[0][0]:.1f},{coords[0][1]:.1f} " + " ".join(
            f"L {x:.1f},{y:.1f}" for x, y in coords[1:]
        )

        # Area fill path (closes down to chart_bottom)
        area_path = (
            f"M {coords[0][0]:.1f},{coords[0][1]:.1f} "
            + " ".join(f"L {x:.1f},{y:.1f}" for x, y in coords)
            + f" L {coords[-1][0]:.1f},{chart_bottom} L {coords[0][0]:.1f},{chart_bottom} Z"
        )
    else:
        line_path = ""
        area_path = ""

    # Daylight rectangle X positions
    solar = data["solar"]
    sunrise_hour = solar["sunrise_min"] / 60.0
    sunset_hour = solar["sunset_min"] / 60.0
    sunrise_x = to_x(sunrise_hour)
    sunset_x = to_x(sunset_hour)

    # Current time marker
    now_hour = data.get("current_hour", 12.0)
    now_level = data.get("current_water_level")
    now_x = to_x(now_hour) if 0 <= now_hour <= 24 else None
    now_y = to_y(now_level) if now_level is not None else None

    # Extrema callout pills
    extrema_svg = []
    pill_offset = 48 if is_clean_graph else 26
    pill_margin_x = 100 if is_clean_graph else 60

    for ext in data.get("today_extrema", []):
        cx = to_x(ext["hour"])
        cy = to_y(ext["height"])
        is_high = ext["is_high"]
        # Position pill above crest or below trough
        pill_y = max(chart_top + 34, cy - pill_offset) if is_high else min(chart_bottom - 34, cy + pill_offset)
        pill_x = min(chart_right - pill_margin_x, max(chart_left + pill_margin_x, cx))

        extrema_svg.append({
            "cx": round(cx, 1),
            "cy": round(cy, 1),
            "pill_x": round(pill_x, 1),
            "pill_y": round(pill_y, 1),
            "height_str": ext["height_str"],
            "time_str": ext["time_str"],
            "is_high": is_high
        })

    # Y Gridlines (e.g. 0, 2, 4, 6 ft)
    y_grids = []
    for level in range(math.floor(min_val), math.ceil(max_val) + 1):
        if level % 2 == 0 or level == 0:
            y_pos = to_y(float(level))
            if chart_top <= y_pos <= chart_bottom:
                is_zero = (level == 0)
                label = "0.0 MLLW" if is_zero else f"{level:+.1f} ft"
                y_grids.append({
                    "y": round(y_pos, 1),
                    "label": label,
                    "is_zero": is_zero
                })

    # X Ticks every 3 hours
    x_ticks = []
    tick_hours = [0, 3, 6, 9, 12, 15, 18, 21, 24]
    tick_labels = ["12 AM", "3 AM", "6 AM", "9 AM", "12 PM", "3 PM", "6 PM", "9 PM", "12 AM"]
    for h, label in zip(tick_hours, tick_labels):
        x_ticks.append({
            "x": round(to_x(h), 1),
            "label": label
        })

    return {
        "chart_left": round(chart_left, 1),
        "chart_right": round(chart_right, 1),
        "chart_top": round(chart_top, 1),
        "chart_bottom": round(chart_bottom, 1),
        "chart_width": round(chart_width, 1),
        "chart_height": round(chart_height, 1),
        "line_path": line_path,
        "area_path": area_path,
        "sunrise_x": round(sunrise_x, 1),
        "sunset_x": round(sunset_x, 1),
        "now_x": round(now_x, 1) if now_x is not None else None,
        "now_y": round(now_y, 1) if now_y is not None else None,
        "extrema_svg": extrema_svg,
        "y_grids": y_grids,
        "x_ticks": x_ticks
    }

def find_headless_browser() -> Optional[str]:
    """Find available Chrome, Chromium, or Edge binary."""
    # Check PATH first
    for name in ["chromium-browser", "chromium", "google-chrome", "chrome", "msedge"]:
        path = shutil.which(name)
        if path:
            return path

    # Common Windows locations
    win_paths = [
        "C:/Program Files/Google/Chrome/Application/chrome.exe",
        "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
        "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
        "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
    ]
    for p in win_paths:
        if os.path.exists(p):
            return p

    # Common Linux / Raspberry Pi locations
    linux_paths = [
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
    ]
    for p in linux_paths:
        if os.path.exists(p):
            return p

    return None

def dither_to_spectra6(rgb_image_path: str, output_path: str) -> None:
    """
    Quantize an RGB image to the 6-color Spectra 6 palette using Floyd-Steinberg error diffusion.
    Saves an indexed 'P' mode PNG optimized for e-paper screens.
    """
    img = Image.open(rgb_image_path).convert("RGB")
    palette_img = Image.new("P", (1, 1))
    palette_img.putpalette(SPECTRA6_PALETTE_256)

    # Apply Floyd-Steinberg dithering
    dithered = img.quantize(palette=palette_img, dither=Image.Dither.FLOYDSTEINBERG)
    dithered.save(output_path, "PNG", optimize=True)

class TideCalendarRenderer:
    def __init__(self, config_path: str = "config.yaml"):
        self.config = load_config(config_path)
        self.width = self.config["display"]["width"]
        self.height = self.config["display"]["height"]
        self.output_dir = "output"
        os.makedirs(self.output_dir, exist_ok=True)

        template_dir = os.path.abspath("templates")
        self.jinja_env = Environment(loader=FileSystemLoader(template_dir))

    def render_html(self, data: Dict[str, Any]) -> str:
        """Render data to HTML file based on view_mode configuration."""
        view_mode = self.config.get("display", {}).get("view_mode", "clean_graph")
        is_clean_graph = (view_mode == "clean_graph")

        chart_data = build_svg_chart_data(data, is_clean_graph=is_clean_graph)
        template_name = "clean_graph.html" if is_clean_graph else "tide_calendar.html"
        template = self.jinja_env.get_template(template_name)
        html_content = template.render(chart=chart_data, **data)

        out_html = os.path.abspath(os.path.join(self.output_dir, "tide_calendar.html"))
        with open(out_html, "w", encoding="utf-8") as f:
            f.write(html_content)

        # Copy style files to output dir
        for style_name in ["style.css", "clean_graph.css"]:
            src = os.path.join("templates", style_name)
            dst = os.path.join(self.output_dir, style_name)
            if os.path.exists(src):
                shutil.copy2(src, dst)

        return out_html

    def render_image(self, target_date: Optional[Any] = None) -> Dict[str, str]:
        """
        Complete end-to-end rendering pipeline:
        1. Fetch data
        2. Render HTML
        3. Capture 1600x1200 screenshot
        4. Dither to Spectra 6 palette
        Returns dictionary of output file paths.
        """
        fetcher = TideDataFetcher()
        data = fetcher.get_complete_tide_data(target_date)

        # 1. Render HTML
        html_path = self.render_html(data)

        # 2. Screenshot with headless browser
        browser = find_headless_browser()
        if not browser:
            raise RuntimeError("No suitable headless browser (Chrome/Chromium/Edge) found for screenshot capture.")

        rgb_png_path = os.path.abspath(os.path.join(self.output_dir, "tide_calendar_1600x1200.png"))
        file_url = "file:///" + html_path.replace("\\", "/")

        cmd = [
            browser,
            "--headless=new",
            f"--screenshot={rgb_png_path}",
            f"--window-size={self.width},{self.height}",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            file_url
        ]

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0 or not os.path.exists(rgb_png_path):
            raise RuntimeError(f"Browser screenshot failed: {res.stderr}")

        # 3. Dither to Spectra 6 Palette
        spectra6_png_path = os.path.abspath(os.path.join(self.output_dir, "tide_calendar_spectra6.png"))
        dither_to_spectra6(rgb_png_path, spectra6_png_path)

        return {
            "html": html_path,
            "rgb_png": rgb_png_path,
            "spectra6_png": spectra6_png_path
        }

if __name__ == "__main__":
    renderer = TideCalendarRenderer()
    print("Rendering Encinitas Tide Calendar...")
    res = renderer.render_image()
    print(f"Generated HTML: {res['html']}")
    print(f"Generated RGB PNG: {res['rgb_png']} ({os.path.getsize(res['rgb_png']) / 1024:.1f} KB)")
    print(f"Generated Spectra 6 PNG: {res['spectra6_png']} ({os.path.getsize(res['spectra6_png']) / 1024:.1f} KB)")
