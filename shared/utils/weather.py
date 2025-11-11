"""
Weather utility for fetching weather data from Open-Meteo API.
No API key required.
"""
import requests
import logging
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

# Open-Meteo API base URL (free, no API key required)
GEOCODING_API = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_API = "https://api.open-meteo.com/v1/forecast"
HISTORICAL_API = "https://archive-api.open-meteo.com/v1/archive"


def get_coordinates_from_zip(zip_code: str) -> Optional[tuple[float, float]]:
    """
    Get latitude and longitude from a US zip code.
    Returns (latitude, longitude) or None if not found.
    """
    try:
        # For US zip codes, we can use a simple geocoding service
        # Using Open-Meteo's geocoding API
        response = requests.get(
            GEOCODING_API,
            params={
                "name": zip_code,
                "count": 1,
                "language": "en",
                "format": "json"
            },
            timeout=5
        )
        response.raise_for_status()
        data = response.json()
        
        if data.get("results") and len(data["results"]) > 0:
            result = data["results"][0]
            lat = result.get("latitude")
            lon = result.get("longitude")
            if lat and lon:
                logger.info(f"Found coordinates for zip {zip_code}: ({lat}, {lon})")
                return (lat, lon)
        
        # Fallback: try with "USA" suffix
        response = requests.get(
            GEOCODING_API,
            params={
                "name": f"{zip_code}, USA",
                "count": 1,
                "language": "en",
                "format": "json"
            },
            timeout=5
        )
        response.raise_for_status()
        data = response.json()
        
        if data.get("results") and len(data["results"]) > 0:
            result = data["results"][0]
            lat = result.get("latitude")
            lon = result.get("longitude")
            if lat and lon:
                logger.info(f"Found coordinates for zip {zip_code}: ({lat}, {lon})")
                return (lat, lon)
        
        logger.warning(f"Could not find coordinates for zip code: {zip_code}")
        return None
    except Exception as e:
        logger.error(f"Error getting coordinates for zip {zip_code}: {e}")
        return None


def get_current_weather(latitude: float, longitude: float) -> Optional[Dict[str, Any]]:
    """
    Get current weather conditions.
    Returns a dictionary with weather data or None on error.
    """
    try:
        response = requests.get(
            WEATHER_API,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                "timezone": "auto",
                "forecast_days": 1
            },
            timeout=5
        )
        response.raise_for_status()
        data = response.json()
        
        current = data.get("current", {})
        if not current:
            return None
        
        # Map weather code to description
        weather_code = current.get("weather_code", 0)
        weather_desc = _get_weather_description(weather_code)
        
        # Convert temperature from Celsius to Fahrenheit
        temp_c = current.get("temperature_2m")
        temp_f = (temp_c * 9/5) + 32 if temp_c is not None else None
        
        weather_data = {
            "temperature": temp_f,
            "humidity": current.get("relative_humidity_2m"),
            "weather_code": weather_code,
            "weather_description": weather_desc,
            "wind_speed": current.get("wind_speed_10m"),
            "timestamp": current.get("time", datetime.now().isoformat())
        }
        
        logger.debug(f"Fetched current weather: {weather_data}")
        return weather_data
    except Exception as e:
        logger.error(f"Error fetching current weather: {e}")
        return None


def get_historical_weather(latitude: float, longitude: float, timestamp: datetime) -> Optional[Dict[str, Any]]:
    """
    Get historical weather for a specific timestamp.
    Returns a dictionary with weather data or None on error.
    """
    try:
        # Format date for API (YYYY-MM-DD)
        date_str = timestamp.strftime("%Y-%m-%d")
        
        response = requests.get(
            HISTORICAL_API,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "start_date": date_str,
                "end_date": date_str,
                "hourly": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                "timezone": "auto"
            },
            timeout=5
        )
        response.raise_for_status()
        data = response.json()
        
        hourly = data.get("hourly", {})
        if not hourly or not hourly.get("time"):
            return None
        
        # Find the closest hour to the timestamp
        times = hourly.get("time", [])
        temperatures = hourly.get("temperature_2m", [])
        humidities = hourly.get("relative_humidity_2m", [])
        weather_codes = hourly.get("weather_code", [])
        wind_speeds = hourly.get("wind_speed_10m", [])
        
        # Find closest hour
        target_hour = timestamp.hour
        closest_idx = 0
        min_diff = 24
        
        for i, time_str in enumerate(times):
            try:
                time_obj = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                hour_diff = abs(time_obj.hour - target_hour)
                if hour_diff < min_diff:
                    min_diff = hour_diff
                    closest_idx = i
            except:
                continue
        
        if closest_idx < len(temperatures):
            weather_code = weather_codes[closest_idx] if closest_idx < len(weather_codes) else 0
            weather_desc = _get_weather_description(weather_code)
            
            # Convert temperature from Celsius to Fahrenheit
            temp_c = temperatures[closest_idx] if closest_idx < len(temperatures) else None
            temp_f = (temp_c * 9/5) + 32 if temp_c is not None else None
            
            weather_data = {
                "temperature": temp_f,
                "humidity": humidities[closest_idx] if closest_idx < len(humidities) else None,
                "weather_code": weather_code,
                "weather_description": weather_desc,
                "wind_speed": wind_speeds[closest_idx] if closest_idx < len(wind_speeds) else None,
                "timestamp": timestamp.isoformat()
            }
            
            logger.debug(f"Fetched historical weather for {timestamp}: {weather_data}")
            return weather_data
        
        return None
    except Exception as e:
        logger.error(f"Error fetching historical weather: {e}")
        return None


def _get_weather_description(code: int) -> str:
    """
    Convert WMO weather code to human-readable description.
    Based on WMO Weather interpretation codes (WW).
    """
    weather_codes = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Foggy",
        48: "Depositing rime fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        56: "Light freezing drizzle",
        57: "Dense freezing drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        66: "Light freezing rain",
        67: "Heavy freezing rain",
        71: "Slight snow fall",
        73: "Moderate snow fall",
        75: "Heavy snow fall",
        77: "Snow grains",
        80: "Slight rain showers",
        81: "Moderate rain showers",
        82: "Violent rain showers",
        85: "Slight snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with slight hail",
        99: "Thunderstorm with heavy hail"
    }
    return weather_codes.get(code, "Unknown")


def get_weather_for_zip(zip_code: str, timestamp: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """
    Get weather for a zip code, either current or historical.
    If timestamp is provided, fetches historical weather.
    Otherwise fetches current weather.
    """
    coords = get_coordinates_from_zip(zip_code)
    if not coords:
        return None
    
    lat, lon = coords
    
    if timestamp:
        return get_historical_weather(lat, lon, timestamp)
    else:
        return get_current_weather(lat, lon)

