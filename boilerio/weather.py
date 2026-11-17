import json
import math
import time
from dataclasses import dataclass
from datetime import timedelta

from .cached_resource import CachedResource

WEATHER_API_ENDPOINT = 'https://api.openweathermap.org/data/2.5/weather'


@dataclass(frozen=True)
class WeatherReading:
    """Weather in Celsius and percent humidity, with Unix sunrise/sunset times."""

    temperature: float
    humidity: float
    sunrise: int
    sunset: int


def parse_weather(text: str) -> WeatherReading:
    """Parse a weather API response into a validated WeatherReading."""
    result = json.loads(text)
    try:
        reading = WeatherReading(
            temperature=float(result['main']['temp']),
            humidity=float(result['main']['humidity']),
            sunrise=int(result['sys']['sunrise']),
            sunset=int(result['sys']['sunset']),
        )
    except OverflowError as e:
        raise ValueError('Weather values must be finite') from e
    if not all(math.isfinite(value) for value in (reading.temperature, reading.humidity)):
        raise ValueError('Weather values must be finite')
    return reading


class Weather:
    """Cached weather observations for a fixed location."""

    def __init__(self, apikey: str, location: str,
                 cache_time: timedelta = timedelta(hours=1), worker=None, clock=time.monotonic):
        self._resource = CachedResource(
            WEATHER_API_ENDPOINT, parse_weather,
            params={'q': location, 'apikey': apikey, 'units': 'metric'},
            update_interval=cache_time, worker=worker, clock=clock)

    def get_weather(self, deadline: float | None = None) -> WeatherReading | None:
        """Return the latest reading, optionally waiting until the monotonic deadline."""
        return self._resource.get(deadline)
