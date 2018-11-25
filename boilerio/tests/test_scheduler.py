# Note that this file should probably be split into two along with
# separation of scheduler policy from the scheduler app.

from mock import Mock
from datetime import time, datetime
from boilerio import model, scheduler
import requests_mock
import requests.exceptions

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

@requests_mock.Mocker()
def test_no_exception_if_request_raises(m):
    m.get("http://scheduler/api/schedule", exc=requests.exceptions.Timeout)
    scheduler.scheduler_iteration(None, None, 'http://scheduler/api', None, None, [])

@requests_mock.Mocker()
def test_no_exception_if_request_fails(m):
    m.get("http://scheduler/api/schedule", status_code=401)
    scheduler.scheduler_iteration(None, None, 'http://scheduler/api', None, None, [])

@requests_mock.Mocker()
def test_copes_with_no_target(m):
    m.get("http://scheduler/api/schedule", text=EMPTY_SCHEDULE_RESPONSE)
    mqttc = Mock()
    now = datetime.now()
    scheduler.scheduler_iteration(mqttc, None, "http://scheduler/api", None, now, [])
    mqttc.publish.assert_not_called()

#
# Scheduler policy tests
#

def test_from_json_one_override():
    """Check JSON parsing for simple configuration with one override."""

    schedule_json_one_override = """{
        "schedule": { "0": [], "1": [], "2": [], "3": [], "4": [], "5": [], 
                      "6": [] },
        "target_override": [ 
            {"zone": 1, "temp": 22, "until": "2018-10-10T10:10"}
        ]
    }"""
    schedule = scheduler.SchedulerTemperaturePolicy.from_json(
        schedule_json_one_override)
    assert schedule.target(datetime(2018, 1, 1, 0, 0), 1) == 22
    assert schedule.target(datetime(2018, 1, 1, 0, 0), 2) == None

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
        schedule_json_one_override)
    # Monday at 11:00 should be 19
    assert schedule.target(datetime(2018, 12, 3, 11, 0), 1) == 19
    # Tuesday at 11:00 should be 20
    assert schedule.target(datetime(2018, 12, 4, 11, 0), 1) == 20

def test_empty_day_carries_forward_last_entry():
    """Carry-forward behaviour for empty days.

    Check that a day with no entries gets the entry from the
    previous day carried forward as a midnight-tomorrow event."""
    schedule = scheduler.SchedulerTemperaturePolicy(
        model.FullSchedule([
            (0, time(12, 0), 1, 20),
            (2, time(0, 0), 1, 22)]),
        [])

    tuesday_midnight = datetime(2017, 1, 3, 0, 0)
    tuesday_midday = datetime(2017, 1, 3, 12, 0)
    wednesday_midday = datetime(2017, 1, 4, 12, 0)
    thursday_midday = datetime(2017, 1, 4, 12, 0)
    monday_early = datetime(2017, 1, 2, 11, 59)
    monday_late = datetime(2017, 1, 2, 12, 1)

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
        [])

    monday = datetime(2017, 1, 2, 1, 0)

    assert schedule.target(monday, 1) == 20
    assert schedule.target(monday, 2) == 22

def test_no_schedule_returns_no_target():
    """Check no target returned if schedule and override are empty."""
    schedule = scheduler.SchedulerTemperaturePolicy(
        model.FullSchedule([]), None)
    assert schedule.target(datetime(2017, 1, 1, 0, 0), 1) == None

def test_scheduler_from_json_empty_schedule():
    """Check policy creation from JSON with empty schedule."""
    schedule = scheduler.SchedulerTemperaturePolicy.from_json(
        EMPTY_SCHEDULE_RESPONSE)
