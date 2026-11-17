# Note that this file should probably be split into two along with
# separation of scheduler policy from the scheduler app.

from datetime import time, datetime, timedelta, timezone
import json
from zoneinfo import ZoneInfo
from unittest.mock import Mock

from .. import scheduler
from ..schedulerweb import model
import requests_mock
import pytest

from .http_helpers import Clock, InlineWorker, iterate_at


def make_controller(*args, **kwargs):
    return scheduler.AllZoneController(*args, fetch_worker=InlineWorker(), clock=Clock(), **kwargs)


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

def test_zones_wait_until_a_schedule_is_available():
    zone = Mock()
    controller = make_controller('https://scheduler/api', None, [zone], LONDON)
    with requests_mock.Mocker() as http:
        http.get('https://scheduler/api/schedule', status_code=503)
        iterate_at(controller, None, 0)
        zone.iteration.assert_not_called()

        http.get('https://scheduler/api/schedule', text=EMPTY_SCHEDULE_RESPONSE)
        iterate_at(controller, None, 60)
        zone.iteration.assert_called_once_with(controller.scheduler, None, 60, 65)


def test_invalid_schedule_refresh_keeps_last_policy_in_control():
    zone = Mock()
    controller = make_controller('https://scheduler/api', None, [zone], LONDON)
    with requests_mock.Mocker() as http:
        http.get('https://scheduler/api/schedule', text=EMPTY_SCHEDULE_RESPONSE)
        iterate_at(controller, None, 0)
        last_policy = controller.scheduler
        zone.reset_mock()

        http.get('https://scheduler/api/schedule', json={'schedule': None, 'target_override': []})
        iterate_at(controller, None, 60)
        zone.iteration.assert_called_once_with(last_policy, None, 60, 65)


def test_offline_schedule_startup_preserves_override_expiry(tmp_path):
    cache = tmp_path / 'schedule'
    cache.write_text(json.dumps({
        'schedule': {'0': [{'when': '00:00', 'zones': [{'zone': 1, 'temp': 18}]}]},
        'target_override': [{'zone': 1, 'temp': 23, 'until': '2026-11-02T12:00:00+00:00'}],
    }))
    zone = Mock()
    controller = make_controller(
        'https://scheduler/api', None, [zone], LONDON, schedule_cache_path=cache)
    controller._schedule_resource.load_backup()
    with requests_mock.Mocker() as http:
        http.get('https://scheduler/api/schedule', status_code=500)
        before = instant(2026, 11, 2, 11, 59, 59)
        iterate_at(controller, before, 0)
        assert controller.scheduler.target(before, 1) == 23
        after = before + timedelta(seconds=1)
        iterate_at(controller, after, 1)
        assert controller.scheduler.target(after, 1) == 18
        assert http.call_count == 1
        zone.iteration.assert_called_with(controller.scheduler, after, 1, 1 + controller.FETCH_WAIT_SECONDS)


#
# Scheduler policy tests
#

@pytest.mark.parametrize('temperature', ['bad', True, float('nan'), float('inf')])
def test_invalid_schedule_temperature_is_rejected_before_control(temperature):
    payload = {'schedule': {'0': [{'when': '00:00', 'zones': [{'zone': 1, 'temp': temperature}]}]},
               'target_override': []}
    with pytest.raises(ValueError, match='finite temperature'):
        scheduler.SchedulerTemperaturePolicy.from_json(json.dumps(payload), LONDON)

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
