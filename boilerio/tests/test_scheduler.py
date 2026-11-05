# Note that this file should probably be split into two along with
# separation of scheduler policy from the scheduler app.

from datetime import time, datetime, timedelta, timezone
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .. import scheduler
from ..schedulerweb import model
import requests_mock
import requests.exceptions
import pytest

LONDON = ZoneInfo("Europe/London")


def instant(*args):
    return datetime(*args, tzinfo=timezone.utc)


EMPTY_SCHEDULE_RESPONSE = """{
   "schedule": {
       "0": [],
       "1": [],
       "2": [],
       "3": [],
       "4": [],
       "5": [],
       "6": []
   },
   "target_override": []
}"""

#
# Scheduler tests
#

def test_no_exception_if_request_raises():
    with requests_mock.Mocker() as m:
        m.get("https://scheduler/api/schedule", exc=requests.exceptions.Timeout)
        zc = scheduler.AllZoneController('https://scheduler/api', None, [], LONDON)
        zc.iteration(None, 0)

def test_no_exception_if_request_fails():
    with requests_mock.Mocker() as m:
        m.get("https://scheduler/api/schedule", status_code=401)
        zc = scheduler.AllZoneController('https://scheduler/api', None, [], LONDON)
        zc.iteration(None, 0)


def test_cached_response_used_when_web_service_is_offline(monkeypatch, tmp_path):
    def offline(*args, **kwargs):
        raise requests.exceptions.ConnectionError("offline")

    monkeypatch.setattr(scheduler.requests, 'get', offline)
    backup = tmp_path / 'zones'
    backup.write_text('[{"zone_id": 1}]')
    assert scheduler.get_url_with_fallback(
        str(backup), 'https://scheduler/zones', None) == '[{"zone_id": 1}]'


def test_zone_and_sensor_load_accept_cached_responses(monkeypatch):
    def cached_response(fallback, url, auth):
        if url.endswith('/zones'):
            return '[{"zone_id": 1, "name": "living", "boiler_relay": "0x1", "sensor_id": 2}]'
        return '[{"sensor_id": 2, "locator": "sensors/living"}]'

    monkeypatch.setattr(scheduler, 'get_url_with_fallback', cached_response)
    assert scheduler.load_zone_info('https://scheduler', None)[0].zone_id == 1
    assert scheduler.construct_sensors('https://scheduler', None)[2].locator == 'sensors/living'


def test_zone_and_sensor_load_raise_when_offline_without_cache(monkeypatch):
    monkeypatch.setattr(scheduler, 'get_url_with_fallback',
                        lambda fallback, url, auth: None)
    with pytest.raises(scheduler.ZoneInfoUnavailable):
        scheduler.load_zone_info('https://scheduler', None)
    with pytest.raises(scheduler.ZoneInfoUnavailable):
        scheduler.construct_sensors('https://scheduler', None)


@pytest.mark.parametrize('loader,endpoint,payload,invalid,read_result', [
    (scheduler.load_system_timezone, '/system', {'timezone': 'Europe/London'},
     {'timezone': 'Invalid/Zone'}, lambda result: result.key),
    (scheduler.load_zone_info, '/zones',
     [{'zone_id': 1, 'name': 'Room', 'boiler_relay': '0x1', 'sensor_id': 2}],
     [{'zone_id': 1}], lambda result: result[0].name),
    (scheduler.construct_sensors, '/sensor/', [{'sensor_id': 2, 'locator': 'sensor/2'}],
     [{'sensor_id': 2}], lambda result: result[2].locator),
])
def test_loaders_parse_online_and_cached_responses_consistently(
        monkeypatch, tmp_path, loader, endpoint, payload, invalid, read_result):
    cache = tmp_path / 'cache'
    fetch = scheduler.get_url_with_fallback
    monkeypatch.setattr(scheduler, 'get_url_with_fallback',
                        lambda fallback, url, auth: fetch(cache, url, auth))
    with requests_mock.Mocker() as requests:
        requests.get('http://scheduler' + endpoint, json=payload)
        original = read_result(loader('http://scheduler', None))
        assert json.loads(cache.read_text()) == payload
        requests.get('http://scheduler' + endpoint, status_code=503)
        assert read_result(loader('http://scheduler', None)) == original
        requests.get('http://scheduler' + endpoint, json=invalid)
        with pytest.raises((ValueError, KeyError, TypeError)):
            loader('http://scheduler', None)
        assert json.loads(cache.read_text()) == invalid
        requests.get('http://scheduler' + endpoint, status_code=503)
        with pytest.raises((ValueError, KeyError, TypeError)):
            loader('http://scheduler', None)


def test_cache_creation_failure_does_not_discard_valid_response(tmp_path):
    cache = tmp_path / 'missing-directory' / 'cache'
    with requests_mock.Mocker() as requests:
        requests.get('http://scheduler/config', json={'value': 'new'})
        assert json.loads(scheduler.get_url_with_fallback(cache, 'http://scheduler/config', None)) == {'value': 'new'}
    assert not cache.exists()


def test_helper_returns_cached_text_without_parsing(tmp_path):
    cache = tmp_path / 'cache'
    cache.write_text('not json')
    with requests_mock.Mocker() as requests:
        requests.get('http://scheduler/config', status_code=503)
        assert scheduler.get_url_with_fallback(cache, 'http://scheduler/config', None) == 'not json'

def test_system_configuration_cache_and_invalid_response(tmp_path):
    cache = tmp_path / 'system'
    url = 'http://scheduler/system'
    with requests_mock.Mocker() as requests:
        requests.get(url, json={'timezone': 'Europe/London'})
        assert scheduler.load_system_timezone('http://scheduler', None, cache).key == 'Europe/London'
        requests.get(url, status_code=503)
        assert scheduler.load_system_timezone('http://scheduler', None, cache).key == 'Europe/London'
        requests.get(url, json={'timezone': 'Invalid/Zone'})
        with pytest.raises(ZoneInfoNotFoundError):
            scheduler.load_system_timezone('http://scheduler', None, cache)
        requests.get(url, text='invalid json')
        with pytest.raises(ValueError):
            scheduler.load_system_timezone('http://scheduler', None, cache)
        assert cache.read_text() == 'invalid json'
        requests.get(url, status_code=503)
        with pytest.raises(ValueError):
            scheduler.load_system_timezone('http://scheduler', None, cache)
        cache.unlink()
        requests.get(url, status_code=503)
        with pytest.raises(ValueError, match='No heating timezone'):
            scheduler.load_system_timezone('http://scheduler', None, cache)


#
# Scheduler policy tests
#

def test_from_json_one_override():
    """Check JSON parsing for simple configuration with one override."""

    schedule_json_one_override = """{
        "schedule": { "0": [], "1": [], "2": [], "3": [], "4": [], "5": [],
                      "6": [] },
        "target_override": [
            {"zone": 1, "temp": 22, "until": "2018-10-10T10:10:00+00:00"}
        ]
    }"""
    schedule = scheduler.SchedulerTemperaturePolicy.from_json(
        schedule_json_one_override, LONDON)
    assert schedule.target(instant(2018, 1, 1, 0, 0), 1) == 22
    assert schedule.target(instant(2018, 1, 1, 0, 0), 2) == None

def test_from_json_simple_schedule():
    """Check JSON parsing for simple configuration with one override."""

    schedule_json_one_override = """{
        "schedule": { "0": [{
                        "when": "10:00",
                        "zones": [{ "temp": 19, "zone": 1 }]
                        }],
                      "1": [{
                        "when": "10:00",
                        "zones": [{"temp": 20, "zone": 1 }]
                        }],
                      "2": [], "3": [], "4": [], "5": [], "6": [] },
        "target_override": []
    }"""
    schedule = scheduler.SchedulerTemperaturePolicy.from_json(
        schedule_json_one_override, LONDON)
    # Monday at 11:00 should be 19
    assert schedule.target(instant(2018, 12, 3, 11, 0), 1) == 19
    # Tuesday at 11:00 should be 20
    assert schedule.target(instant(2018, 12, 4, 11, 0), 1) == 20

def test_empty_day_carries_forward_last_entry():
    """Carry-forward behaviour for empty days.

    Check that a day with no entries gets the entry from the
    previous day carried forward as a midnight-tomorrow event."""
    schedule = scheduler.SchedulerTemperaturePolicy(
        model.FullSchedule([
            (0, time(12, 0), 1, 20),
            (2, time(0, 0), 1, 22)]),
        [], LONDON)

    tuesday_midnight = instant(2017, 1, 3, 0, 0)
    tuesday_midday = instant(2017, 1, 3, 12, 0)
    wednesday_midday = instant(2017, 1, 4, 12, 0)
    thursday_midday = instant(2017, 1, 4, 12, 0)
    monday_early = instant(2017, 1, 2, 11, 59)
    monday_late = instant(2017, 1, 2, 12, 1)

    assert schedule.target(tuesday_midnight, 1) == 20
    assert schedule.target(tuesday_midday, 1) == 20
    assert schedule.target(wednesday_midday, 1) == 22
    assert schedule.target(thursday_midday, 1) == 22
    assert schedule.target(monday_early, 1) == 22
    assert schedule.target(monday_late, 1) == 20

def test_zones_dont_interfere():
    """Check target when two zones change simultaneously/"""
    schedule = scheduler.SchedulerTemperaturePolicy(
        model.FullSchedule([
            (0, time(12, 0), 1, 20),
            (0, time(12, 0), 2, 22)]),
        [], LONDON)

    monday = instant(2017, 1, 2, 1, 0)

    assert schedule.target(monday, 1) == 20
    assert schedule.target(monday, 2) == 22

def test_zones_changing_simultaneously():
    schedule_json_changing_simultaneously = """{
        "schedule": { "0": [{
                        "when": "10:00",
                        "zones": [{ "temp": 19, "zone": 1 }]
                        }, {
                        "when": "11:00",
                        "zones": [{"temp": 20, "zone": 2 }]
                        }, {
                        "when": "12:00",
                        "zones": [{"temp": 15, "zone": 1 },
                                  {"temp": 16, "zone": 2 }]
                        }],
                      "1": [], "2": [], "3": [], "4": [], "5": [], "6": [] },
        "target_override": []
    }"""
    schedule = scheduler.SchedulerTemperaturePolicy.from_json(
        schedule_json_changing_simultaneously, LONDON)

    # Monday at 10:30 should be 19 in zone 1
    assert schedule.target(instant(2018, 12, 3, 10, 30), 1) == 19
    # Monday at 12:30 should be 20 in zone 2
    assert schedule.target(instant(2018, 12, 3, 11, 30), 2) == 20
    # Monday at 13:30 should be 15 and 16 respectively in zones 1 and 2
    assert schedule.target(instant(2018, 12, 3, 12, 30), 1) == 15
    assert schedule.target(instant(2018, 12, 3, 12, 30), 2) == 16

def test_no_schedule_returns_no_target():
    """Check no target returned if schedule and override are empty."""
    schedule = scheduler.SchedulerTemperaturePolicy(
        model.FullSchedule([]), None, LONDON)
    assert schedule.target(instant(2017, 1, 1, 0, 0), 1) == None

def test_scheduler_from_json_empty_schedule():
    """Check policy creation from JSON with empty schedule."""
    scheduler.SchedulerTemperaturePolicy.from_json(
        EMPTY_SCHEDULE_RESPONSE, LONDON)


@pytest.mark.parametrize('before,after', [
    ('2026-01-05T06:59:00+00:00', '2026-01-05T07:00:00+00:00'),
    ('2026-07-06T05:59:00+00:00', '2026-07-06T06:00:00+00:00'),
])
def test_weekly_schedule_stays_at_seven_local(before, after):
    policy = scheduler.SchedulerTemperaturePolicy(
        model.FullSchedule([(0, time(7), 1, 20), (0, time(22), 1, 15)]), [],
        ZoneInfo('Europe/London'))
    assert policy.target(datetime.fromisoformat(before), 1) == 15
    assert policy.target(datetime.fromisoformat(after), 1) == 20


def test_spring_gap_and_repeated_autumn_hour_follow_local_clock():
    policy = scheduler.SchedulerTemperaturePolicy(
        model.FullSchedule([(6, time(0), 1, 15), (6, time(1, 30), 1, 20)]), [],
        ZoneInfo('Europe/London'))
    for instant, expected in [
        ('2026-03-29T00:59:59+00:00', 15), ('2026-03-29T01:00:00+00:00', 20),
        ('2026-10-25T00:30:00+00:00', 20), ('2026-10-25T01:00:00+00:00', 15),
        ('2026-10-25T01:30:00+00:00', 20),
    ]:
        assert policy.target(datetime.fromisoformat(instant), 1) == expected


def test_override_expiry_is_instant_based_and_retains_seconds():
    end = datetime.fromisoformat('2026-10-25T01:30:20.123456+00:00')
    override = model.TargetOverride(end, 23, 1)
    policy = scheduler.SchedulerTemperaturePolicy.from_json(
        json.dumps({'schedule': {}, 'target_override': [override.to_dict()]}),
        ZoneInfo('Europe/London'))
    assert policy.target(end - timedelta(microseconds=1), 1) == 23
    assert not policy.target_overridden(end, 1)
    # Both occurrences of 01:30 London are distinguished.
    assert policy.target_overridden(datetime.fromisoformat('2026-10-25T01:30:30+01:00'), 1)
    assert not policy.target_overridden(datetime.fromisoformat('2026-10-25T01:30:30+00:00'), 1)


def test_override_expiry_with_shared_named_timezone_during_repeated_hour():
    zone = ZoneInfo('Europe/London')
    end = datetime(2026, 10, 25, 1, 45, tzinfo=zone, fold=0)
    now = datetime(2026, 10, 25, 1, 15, tzinfo=zone, fold=1)
    policy = scheduler.SchedulerTemperaturePolicy(
        model.FullSchedule([]), [model.TargetOverride(end, 23, 1)], zone)
    # The first 01:45 has already passed by the second 01:15.
    assert not policy.target_overridden(now, 1)
    assert policy.target(now, 1) is None
