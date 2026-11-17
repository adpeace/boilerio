import json

import pytest
import requests_mock

from boilerio import weather
from .http_helpers import InlineWorker


RESPONSE = {
    'main': {'temp': 9.42, 'humidity': 76},
    'sys': {'sunrise': 1546243745, 'sunset': 1546271815},
}
READING = weather.WeatherReading(9.42, 76.0, 1546243745, 1546271815)


def test_weather_parses_reading_and_sends_query_parameters():
    service = weather.Weather('apikey', 'Girton,GB', worker=InlineWorker())
    with requests_mock.Mocker() as http:
        http.get(weather.WEATHER_API_ENDPOINT, json=RESPONSE)
        assert service.get_weather() == READING
        assert http.last_request.qs == {
            'q': ['girton,gb'], 'apikey': ['apikey'], 'units': ['metric'],
        }
        assert http.last_request.timeout == 10


@pytest.mark.parametrize('section,field,value', [
    ('main', 'temp', 'nan'), ('main', 'humidity', 'inf'), ('sys', 'sunrise', float('inf')),
])
def test_weather_rejects_nonfinite_readings(section, field, value):
    payload = {**RESPONSE, section: {**RESPONSE[section], field: value}}
    with pytest.raises(ValueError, match='finite'):
        weather.parse_weather(json.dumps(payload))
