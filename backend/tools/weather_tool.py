from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode

import httpx


class WeatherTool:
    name = "weather"
    description = "用于查询城市实时天气、气温、降水和风力等结构化天气数据"

    WEATHER_WORDS = ("天气", "气温", "温度", "降雨", "下雨", "风力", "湿度")
    REMOVE_WORDS = (
        "今天",
        "今日",
        "现在",
        "当前",
        "实时",
        "日期",
        "天气",
        "气温",
        "温度",
        "怎么样",
        "如何",
        "多少",
        "查询",
        "查一下",
        "帮我查",
        "帮我搜",
        "请问",
        "一下",
    )
    WEATHER_CODE_MAP = {
        0: "晴",
        1: "大部晴朗",
        2: "局部多云",
        3: "阴",
        45: "雾",
        48: "雾凇",
        51: "小毛毛雨",
        53: "中等毛毛雨",
        55: "强毛毛雨",
        61: "小雨",
        63: "中雨",
        65: "大雨",
        71: "小雪",
        73: "中雪",
        75: "大雪",
        80: "小阵雨",
        81: "中等阵雨",
        82: "强阵雨",
        95: "雷暴",
        96: "雷暴伴小冰雹",
        99: "雷暴伴大冰雹",
    }

    def can_handle(self, query: str) -> bool:
        normalized = self._normalize(query)
        return any(word in normalized for word in self.WEATHER_WORDS) and bool(self.extract_city(normalized))

    def run(self, query: str, max_results: int = 1) -> list[dict[str, Any]]:
        city = self.extract_city(query)
        if not city:
            return []

        with httpx.Client(timeout=20, follow_redirects=True) as client:
            location = self._geocode(client, city)
            if not location:
                return []
            weather = self._forecast(client, location)
            if not weather:
                return []

        return [self._to_source(query, city, location, weather)]

    def info(self) -> dict[str, str]:
        return {
            "name": self.name,
            "description": self.description,
            "provider": "open_meteo",
        }

    def extract_city(self, query: str) -> str:
        normalized = self._normalize(query)
        cleaned = normalized
        for word in self.REMOVE_WORDS:
            cleaned = cleaned.replace(word, " ")
        cleaned = re.sub(r"[，,。？?！!：:；;\-_/]+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        candidates = [
            token
            for token in cleaned.split(" ")
            if 1 < len(token) <= 12 and re.search(r"[\u4e00-\u9fff]", token)
        ]
        return candidates[-1] if candidates else ""

    def _geocode(self, client: httpx.Client, city: str) -> dict[str, Any] | None:
        response = client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "zh", "format": "json"},
        )
        response.raise_for_status()
        results = response.json().get("results") or []
        return results[0] if results else None

    def _forecast(self, client: httpx.Client, location: dict[str, Any]) -> dict[str, Any] | None:
        params = {
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "current": ",".join(
                [
                    "temperature_2m",
                    "relative_humidity_2m",
                    "apparent_temperature",
                    "precipitation",
                    "weather_code",
                    "wind_speed_10m",
                    "wind_direction_10m",
                ]
            ),
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": location.get("timezone") or "auto",
            "forecast_days": 1,
        }
        response = client.get("https://api.open-meteo.com/v1/forecast", params=params)
        response.raise_for_status()
        data = response.json()
        return data if data.get("current") else None

    def _to_source(
        self,
        query: str,
        city: str,
        location: dict[str, Any],
        weather: dict[str, Any],
    ) -> dict[str, Any]:
        current = weather.get("current") or {}
        current_units = weather.get("current_units") or {}
        daily = weather.get("daily") or {}
        weather_code = int(current.get("weather_code") or 0)
        weather_desc = self.WEATHER_CODE_MAP.get(weather_code, f"WMO 天气代码 {weather_code}")
        place = self._place_name(location)
        forecast_url = "https://api.open-meteo.com/v1/forecast?" + urlencode(
            {
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m,wind_direction_10m",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": location.get("timezone") or "auto",
                "forecast_days": 1,
            }
        )
        content = (
            f"{place}实时天气数据。"
            f"数据时间：{current.get('time')}，天气：{weather_desc}。"
            f"当前气温：{current.get('temperature_2m')}{current_units.get('temperature_2m', '°C')}，"
            f"体感温度：{current.get('apparent_temperature')}{current_units.get('apparent_temperature', '°C')}，"
            f"相对湿度：{current.get('relative_humidity_2m')}{current_units.get('relative_humidity_2m', '%')}，"
            f"降水量：{current.get('precipitation')}{current_units.get('precipitation', 'mm')}，"
            f"风速：{current.get('wind_speed_10m')}{current_units.get('wind_speed_10m', 'km/h')}，"
            f"风向：{current.get('wind_direction_10m')}{current_units.get('wind_direction_10m', '°')}。"
            f"今日最高气温：{self._daily_value(daily, 'temperature_2m_max')}{self._daily_unit(weather, 'temperature_2m_max', '°C')}，"
            f"今日最低气温：{self._daily_value(daily, 'temperature_2m_min')}{self._daily_unit(weather, 'temperature_2m_min', '°C')}，"
            f"今日最大降水概率：{self._daily_value(daily, 'precipitation_probability_max')}{self._daily_unit(weather, 'precipitation_probability_max', '%')}。"
        )
        return {
            "index": 1,
            "source": "Open-Meteo",
            "title": f"{place}实时天气",
            "url": forecast_url,
            "snippet": content,
            "content": content,
            "preview": content[:260],
            "provider": "open_meteo_weather",
            "tool": self.name,
            "query": query,
            "metadata": {
                "city_query": city,
                "latitude": location.get("latitude"),
                "longitude": location.get("longitude"),
                "timezone": location.get("timezone"),
                "weather_code": weather_code,
            },
        }

    def _place_name(self, location: dict[str, Any]) -> str:
        parts = [location.get("name"), location.get("admin1"), location.get("country")]
        return "，".join(str(part) for part in parts if part)

    def _daily_value(self, daily: dict[str, Any], key: str) -> Any:
        values = daily.get(key) or []
        return values[0] if values else ""

    def _daily_unit(self, weather: dict[str, Any], key: str, default: str) -> str:
        return str((weather.get("daily_units") or {}).get(key) or default)

    def _normalize(self, value: str) -> str:
        return str(value or "").strip().lower()
