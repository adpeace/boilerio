import requests_mock
import requests.exceptions
import pytest
import datetime
import json
from datetime import timedelta

from .. import weather

def test_simple_result():
    """Check that the weather info can be parsed."""

    sample_good_output = '{"coord":{"lon":0.08,"lat":52.24},"weather":[{"id":804,"main":"Clouds","description":"overcast clouds","icon":"04d"}],"base":"stations","main":{"temp":282.57,"pressure":1034,"humidity":76,"temp_min":282.15,"temp_max":283.15},"visibility":10000,"wind":{"speed":3.6,"deg":260},"clouds":{"all":90},"dt":1546262760,"sys":{"type":1,"id":1482,"message":0.0031,"country":"GB","sunrise":1546243745,"sunset":1546271815},"id":2648627,"name":"Girton","cod":200}'

    with requests_mock.Mocker() as m:
        m.get(weather.WEATHER_API_ENDPOINT, text=sample_good_output)
        responses = [
                weather.get_weather('apikey', 'Girton,GB'),
                weather.Weather('apikey', 'Girton,GB').get_weather()
                ]
        for resp in responses:
            assert 'temperature' in resp
            assert resp['temperature'] == 282.57
            assert all(x in resp for x in
                    ['temperature', 'humidity', 'sunset', 'sunrise'])


def test_caching_weather_actually_caches():
    """Check that the caching weather class doesn't make too many requests."""

    sample_good_output = '{"coord":{"lon":0.08,"lat":52.24},"weather":[{"id":804,"main":"Clouds","description":"overcast clouds","icon":"04d"}],"base":"stations","main":{"temp":282.57,"pressure":1034,"humidity":76,"temp_min":282.15,"temp_max":283.15},"visibility":10000,"wind":{"speed":3.6,"deg":260},"clouds":{"all":90},"dt":1546262760,"sys":{"type":1,"id":1482,"message":0.0031,"country":"GB","sunrise":1546243745,"sunset":1546271815},"id":2648627,"name":"Girton","cod":200}'
    sample_good_output2 = '{"coord":{"lon":0.08,"lat":52.24},"weather":[{"id":804,"main":"Clouds","description":"overcast clouds","icon":"04d"}],"base":"stations","main":{"temp":288.57,"pressure":1034,"humidity":76,"temp_min":282.15,"temp_max":283.15},"visibility":10000,"wind":{"speed":3.6,"deg":260},"clouds":{"all":90},"dt":1546262760,"sys":{"type":1,"id":1482,"message":0.0031,"country":"GB","sunrise":1546243745,"sunset":1546271815},"id":2648627,"name":"Girton","cod":200}'
    sample_good_rv = {
        'temperature': float(json.loads(sample_good_output)['main']['temp']),
        'humidity': float(json.loads(sample_good_output)['main']['humidity']),
        'sunrise': int(json.loads(sample_good_output)['sys']['sunrise']),
        'sunset': int(json.loads(sample_good_output)['sys']['sunset']),
    }
    sample_good_rv2 = {
        'temperature': float(json.loads(sample_good_output2)['main']['temp']),
        'humidity': float(json.loads(sample_good_output2)['main']['humidity']),
        'sunrise': int(json.loads(sample_good_output2)['sys']['sunrise']),
        'sunset': int(json.loads(sample_good_output2)['sys']['sunset']),
    }

    with requests_mock.Mocker() as m:
        m.get(weather.WEATHER_API_ENDPOINT, text=sample_good_output)
        caching_weather = weather.CachingWeather('apikey', 'Girton,GB', timedelta(hours=1))
        now = datetime.datetime.now()

        # Two requests within the cachign interval should return the same value, even if the online
        # content has changed:
        caching_weather.get_weather(now_fn=lambda: (now))
        m.get(weather.WEATHER_API_ENDPOINT, text=sample_good_output2)
        r2 = caching_weather.get_weather(now_fn=lambda: (now + timedelta(minutes=1)))
        assert r2 == sample_good_rv

        # Outside the caching interval, the new value should be returned:
        r3 = caching_weather.get_weather(now_fn=lambda: (now + timedelta(hours=2)))
        assert r3 == sample_good_rv2


class TestErrorCases(object):
    sample_error_output = '{"cod":"500","message":"Internal error: 500001"}'

    def test_error_response(self):
        """Check that appropriate exception is raised on error."""
        with requests_mock.Mocker() as m:
            m.get(weather.WEATHER_API_ENDPOINT, text=self.sample_error_output,
                    status_code=500)
            with pytest.raises(weather.WeatherServiceError):
                weather.get_weather('apikey', 'Girton,GB')
            with pytest.raises(weather.WeatherServiceError):
                weather.Weather('apikey', 'Girton,GB').get_weather()
