import requests_mock
from mock import MagicMock
from datetime import timedelta, datetime

from boilerio import zones

def test_time_to_target_returns_None_until_initialized():
    with requests_mock.Mocker():
        boiler = MagicMock()
        zone = MagicMock()
        sensor = MagicMock()
        thermostat = MagicMock()
        weather = MagicMock()
        weather.get_weather.return_value = {'temperature': 5}

        thermostat.target = 20
        thermostat.is_heating = True
        sensor.temperature = None

        zc = zones.ZoneController(
            zone, boiler, sensor, thermostat, 'https://scheduler/api', None,
            weather
        )

        # There is no gradient table or last recorded temperature:
        assert zc.get_time_to_target() is None

        sensor.temperature = MagicMock()
        sensor.temperature.reading = 15.0
        sensor.temperature.when = datetime.now()
        zc.temperature_change(sensor)

        # Still no gradient table: should return None:
        assert zc.get_time_to_target() is None

        # Now set a gradient table and check the correct value is used:
        # XXX shouldn't be setting the gradient table directly...
        gradient_table = [{'delta': 5.0, 'gradient': 1.0}]
        zc.gradient_table = gradient_table
        assert zc.get_time_to_target() == timedelta(hours=5)
