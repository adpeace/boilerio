import requests_mock
from unittest.mock import MagicMock
from datetime import timedelta, datetime

from boilerio import zones
from boilerio.weather import WeatherReading


def test_thermostat_updates_when_gradients_are_unavailable():
    thermostat = MagicMock(target=20, is_heating=False)
    weather = MagicMock()
    weather.get_weather.return_value = WeatherReading(5, 76, 0, 0)
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
        weather.get_weather.return_value = WeatherReading(5, 76, 0, 0)

        thermostat.target = 20
        thermostat.is_heating = True
        sensor.reading = None

        zc = zones.ZoneController(
            zone, boiler, sensor, thermostat, 'https://scheduler/api', None,
            weather
        )

        # There is no gradient table or last recorded temperature:
        assert zc.get_time_to_target(WeatherReading(5, 76, 0, 0)) is None

        sensor.reading = MagicMock()
        sensor.reading.temperature = 15.0
        sensor.reading.relative_humidity = 60.0
        sensor.reading.when = datetime.now()
        zc.temperature_change(sensor)

        # Still no gradient table: should return None:
        assert zc.get_time_to_target(WeatherReading(5, 76, 0, 0)) is None

        # Now set a gradient table and check the correct value is used:
        # XXX shouldn't be setting the gradient table directly...
        gradient_table = [{'delta': 5.0, 'gradient': 1.0}]
        zc.gradient_table = gradient_table
        assert zc.get_time_to_target(WeatherReading(5, 76, 0, 0)) == timedelta(hours=5)


def test_iteration_reports_changed_estimate_using_one_weather_fetch():
    thermostat = MagicMock(target=20, is_heating=True)
    sensor = MagicMock()
    sensor.reading.temperature = 15
    weather = MagicMock()
    weather.get_weather.return_value = WeatherReading(5, 76, 0, 0)
    controller = zones.ZoneController(
        MagicMock(zone_id=2), MagicMock(), sensor, thermostat,
        'https://scheduler/api', None, weather)
    policy = MagicMock()
    policy.target.return_value = 20
    policy.target_overridden.return_value = False
    url = 'https://scheduler/api/zones/2/'

    with requests_mock.Mocker() as http:
        http.get(url + 'gradients', json=[{'delta': 10, 'gradient': 1}])
        reports = http.post(url + 'reported_state', status_code=200)
        controller.iteration(policy, None, 0)
        assert reports.last_request.json()['time_to_target'] == 18000
        assert weather.get_weather.call_count == 1

        # A new gradient changes only the estimate, which must trigger a report.
        http.get(url + 'gradients', json=[{'delta': 10, 'gradient': 2}])
        controller.iteration(policy, None, 3600)
        assert reports.call_count == 2
        assert reports.last_request.json()['time_to_target'] == 9000
        assert weather.get_weather.call_count == 2

        controller.iteration(policy, None, 3601)
        assert reports.call_count == 2
        assert weather.get_weather.call_count == 3

        thermostat.is_heating = False
        controller.iteration(policy, None, 3602)
        assert reports.call_count == 3
        assert reports.last_request.json()['time_to_target'] is None
        assert weather.get_weather.call_count == 4


def test_missing_weather_clears_estimates_and_keeps_thermostat_running():
    thermostat = MagicMock(target=20, is_heating=True)
    weather = MagicMock()
    weather.get_weather.return_value = None
    controller = zones.ZoneController(
        MagicMock(zone_id=2), MagicMock(), MagicMock(), thermostat,
        'https://scheduler/api', None, weather)
    controller.reported_state.update(current_outside_temp=5, time_to_target=18000)
    policy = MagicMock()
    policy.target.return_value = 20
    policy.target_overridden.return_value = False

    with requests_mock.Mocker() as http:
        http.get('https://scheduler/api/zones/2/gradients', json=[])
        reports = http.post('https://scheduler/api/zones/2/reported_state', status_code=200)
        controller.iteration(policy, None, 0)

    thermostat.interval_elapsed.assert_called_once_with(0)
    assert reports.last_request.json()['current_outside_temp'] is None
    assert reports.last_request.json()['time_to_target'] is None
