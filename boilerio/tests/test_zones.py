import requests_mock
from unittest.mock import MagicMock
from datetime import timedelta, datetime

from boilerio import zones


def test_thermostat_updates_when_gradients_are_unavailable():
    thermostat = MagicMock(target=20, is_heating=False)
    weather = MagicMock()
    weather.get_weather.return_value = {'temperature': 5}
    controller = zones.ZoneController(
        MagicMock(zone_id=2), MagicMock(), MagicMock(), thermostat,
        'https://scheduler/api', None, weather)
    controller.report_updated_state = MagicMock()
    policy = MagicMock()
    policy.target.return_value = 20
    policy.target_overridden.return_value = False
    with requests_mock.Mocker() as http:
        http.get('https://scheduler/api/zones/2/gradients', status_code=500)
        controller.iteration(policy, None, 0)
    thermostat.interval_elapsed.assert_called_once_with(0)


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
        sensor.reading = None

        zc = zones.ZoneController(
            zone, boiler, sensor, thermostat, 'https://scheduler/api', None,
            weather
        )

        # There is no gradient table or last recorded temperature:
        assert zc.get_time_to_target() is None

        sensor.reading = MagicMock()
        sensor.reading.temperature = 15.0
        sensor.reading.relative_humidity = 60.0
        sensor.reading.when = datetime.now()
        zc.temperature_change(sensor)

        # Still no gradient table: should return None:
        assert zc.get_time_to_target() is None

        # Now set a gradient table and check the correct value is used:
        # XXX shouldn't be setting the gradient table directly...
        gradient_table = [{'delta': 5.0, 'gradient': 1.0}]
        zc.gradient_table = gradient_table
        assert zc.get_time_to_target() == timedelta(hours=5)
