import requests
import logging
from datetime import datetime, timedelta

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

WEATHER_API_ENDPOINT = 'https://api.openweathermap.org/data/2.5/weather'

class WeatherServiceError(Exception):
    pass

def get_weather(apikey, city):
    """Return a simplified weather result:

    Result will be of the format:
        {'temperature': TEMP, 'humidity': HUM, 'sunrise': SUNRISE,
         'sunset': SUNSET}
    where SUNRISE and SUNSET are UNIX times in UTC.
    """
    try:
        r = requests.get(WEATHER_API_ENDPOINT, params={
            'q': city, 'apikey': apikey, 'units': 'metric'})
    except requests.exceptions.ConnectionError as e:
        logger.error("Couldn't get weather: %s", e)
        raise

    if r.status_code == 200:
        result = r.json()
        try:
            return {
                'temperature': float(result['main']['temp']),
                'humidity': float(result['main']['humidity']),
                'sunrise': int(result['sys']['sunrise']),
                'sunset': int(result['sys']['sunset']),
                }
        except Exception as e:
            logger.error("Couldn't get weather: %s (response %s; code %d)",
                    str(e), r.text, r.status_code)
            raise
    else:
        logger.error("Couldn't get weather: response %s; code %d",
                r.text, r.status_code)
        raise WeatherServiceError(r)

class Weather(object):
    """Get weather data for a fixed location and apikey."""
    def __init__(self, apikey, location):
        self.apikey = apikey
        self.location = location

    def get_weather(self):
        """Fetch latest weather."""
        return get_weather(self.apikey, self.location)

class CachingWeather(Weather):
    """Returns weather data for a fixed location/apikey and caches it.

    Used to avoid excessive API calls when the data doesn't change very
    often anyway."""
    def __init__(self, apikey, location, cache_time=timedelta(hours=1)):
        super(CachingWeather, self).__init__(apikey, location)
        self._last_updated = None
        self._cache_time = cache_time
        self._last_result = None

    def get_weather(self, now_fn=lambda: datetime.now()):
        """Fetch weather from cache (if not timed out) or online."""
        now = now_fn()
        if (self._last_result is None or self._last_updated is None or
            self._last_updated + self._cache_time < now):
            try:
                self._last_result = super(CachingWeather, self).get_weather()
                self._last_updated = now
            except WeatherServiceError as e:
                logger.info("Failed to get updated weather information, using "
                        "cached result")
        return self._last_result
