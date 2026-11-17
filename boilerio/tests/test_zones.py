import requests_mock
import requests
import pytest
from unittest.mock import MagicMock
from datetime import timedelta, datetime

from boilerio import zones
from boilerio.weather import WeatherReading
from boilerio.thermostat import Thermostat
from boilerio.tempsensor import SensorReading
from types import SimpleNamespace
from datetime import timezone
from .http_helpers import Clock, HeldWorker, InlineWorker, iterate_at


def test_thermostat_updates_when_gradients_are_unavailable():
    thermostat = MagicMock(target=20, is_heating=False)
    weather = MagicMock()
    weather.get_weather.return_value = WeatherReading(5, 76, 0, 0)
    controller = zones.ZoneController(
        MagicMock(zone_id=2), MagicMock(), MagicMock(), thermostat,
        'https://scheduler/api', None, weather, upload_worker=InlineWorker(),
        fetch_worker=InlineWorker(), clock=Clock())
    controller.report_updated_state = MagicMock()
    policy = MagicMock()
    policy.target.return_value = 20
    policy.target_overridden.return_value = False
    with requests_mock.Mocker() as http:
        gradients = http.get('https://scheduler/api/zones/2/gradients', status_code=500)
        controller.iteration(policy, None, 0)
        assert gradients.call_count == 1
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
            weather, upload_worker=InlineWorker()
        )

        # There is no gradient table or last recorded temperature:
        assert zc.get_time_to_target(WeatherReading(5, 76, 0, 0)) is None

        sensor.reading = MagicMock()
        sensor.reading.temperature = 15.0
        sensor.reading.relative_humidity = 60.0
        sensor.reading.when = datetime.now()

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
        'https://scheduler/api', None, weather, upload_worker=InlineWorker(),
        fetch_worker=InlineWorker(), clock=Clock())
    policy = MagicMock()
    policy.target.return_value = 20
    policy.target_overridden.return_value = False
    url = 'https://scheduler/api/zones/2/'

    with requests_mock.Mocker() as http:
        http.get(url + 'gradients', json=[{'delta': 10, 'gradient': 1}])
        reports = http.post(url + 'reported_state', status_code=200)
        iterate_at(controller, policy, None, 0)
        assert reports.last_request.json()['time_to_target'] == 18000
        assert weather.get_weather.call_count == 1

        # A new gradient changes only the estimate, which must trigger a report.
        http.get(url + 'gradients', json=[{'delta': 10, 'gradient': 2}])
        iterate_at(controller, policy, None, 3600)
        assert reports.call_count == 2
        assert reports.last_request.json()['time_to_target'] == 9000
        assert weather.get_weather.call_count == 2

        iterate_at(controller, policy, None, 3601)
        assert reports.call_count == 2
        assert weather.get_weather.call_count == 3

        thermostat.is_heating = False
        iterate_at(controller, policy, None, 3602)
        assert reports.call_count == 3
        assert reports.last_request.json()['time_to_target'] is None
        assert weather.get_weather.call_count == 4


def test_missing_weather_clears_estimates_and_keeps_thermostat_running():
    thermostat = MagicMock(target=20, is_heating=True)
    weather = MagicMock()
    weather.get_weather.return_value = None
    sensor = MagicMock(reading=None)
    controller = zones.ZoneController(
        MagicMock(zone_id=2), MagicMock(), sensor, thermostat,
        'https://scheduler/api', None, weather, upload_worker=InlineWorker())
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


@pytest.mark.parametrize('failure', [
    pytest.param({'exc': requests.exceptions.Timeout}, id='timeout'),
    pytest.param({'status_code': 503}, id='unavailable'),
])
def test_failed_zone_upload_retries_latest_state_one_minute_after_completion(failure):
    clock, worker = Clock(), HeldWorker()
    sensor = MagicMock()
    sensor.reading.temperature = 17
    thermostat = MagicMock(target=20, is_heating=False)
    weather = MagicMock()
    weather.get_weather.return_value = None
    controller = zones.ZoneController(
        MagicMock(zone_id=2), MagicMock(), sensor, thermostat,
        'https://scheduler/api', None, weather, upload_worker=worker, clock=clock)
    policy = MagicMock()
    policy.target.return_value = 20
    policy.target_overridden.return_value = False
    with requests_mock.Mocker() as http:
        url = 'https://scheduler/api/zones/2/reported_state'
        http.post(url, **failure)
        controller.iteration(policy, None, 0)
        clock.value = 130
        worker.run_next()

        sensor.reading.temperature = 18
        iterate_at(controller, policy, None, 189)
        thermostat.interval_elapsed.assert_called_with(189)
        assert not worker.jobs

        reports = http.post(url, status_code=200)
        iterate_at(controller, policy, None, 190)
        worker.run_next()
        assert reports.last_request.json()['current_temp'] == 18
        iterate_at(controller, policy, None, 191)
        assert not worker.jobs

        sensor.reading.temperature = 19
        iterate_at(controller, policy, None, 192)
        worker.run_next()
        assert reports.last_request.json()['current_temp'] == 19


@pytest.mark.parametrize('gradient', [0, -1, float('nan'), float('inf')])
def test_unusable_heating_gradient_disables_eta_without_stopping_control(gradient):
    boiler = MagicMock()
    sensor = SimpleNamespace(reading=SensorReading(datetime.now(timezone.utc), 15, 70, 0))
    thermostat = Thermostat(boiler, sensor)
    weather = MagicMock()
    weather.get_weather.return_value = WeatherReading(5, 70, 0, 0)
    controller = zones.ZoneController(SimpleNamespace(zone_id=1), boiler, sensor, thermostat,
                                      'http://scheduler', None, weather, upload_worker=InlineWorker())
    controller._gradient_resource.value = [{'delta': 10, 'gradient': gradient}]
    policy = MagicMock()
    policy.target.return_value = 20
    policy.target_overridden.return_value = False
    with requests_mock.Mocker() as http:
        reports = http.post('http://scheduler/zones/1/reported_state', status_code=200)
        controller.iteration(policy, None, 0)
    boiler.on.assert_called_once()
    assert reports.last_request.json()['time_to_target'] is None
