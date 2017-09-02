from datetime import time, datetime
import model
import scheduler
import requests_mock
import requests.exceptions

@requests_mock.Mocker()
def test_no_exception_if_request_raises(m):
    m.get("http://scheduler/api/schedule", exc=requests.exceptions.Timeout)
    scheduler.scheduler_iteration(None, None, 'http://scheduler/api', None, None)

@requests_mock.Mocker()
def test_no_exception_if_request_fails(m):
    m.get("http://scheduler/api/schedule", status_code=401)
    scheduler.scheduler_iteration(None, None, 'http://scheduler/api', None, None)

def test_empty_day_carries_forward_last_entry():
    """Carry-forward behaviour for empty days.

    Check that a day with no entries gets the entry from the
    previous day carried forward as a midnight-tomorrow event."""
    schedule = scheduler.SchedulerTemperaturePolicy(
        model.FullSchedule([
            (0, time(12, 0), 20),
            (2, time(0, 0), 22)]),
        None)

    tuesday_midnight = datetime(2017, 1, 3, 0, 0)
    tuesday_midday = datetime(2017, 1, 3, 12, 0)
    wednesday_midday = datetime(2017, 1, 4, 12, 0)
    thursday_midday = datetime(2017, 1, 4, 12, 0)
    monday_early = datetime(2017, 1, 2, 11, 59)
    monday_late = datetime(2017, 1, 2, 12, 1)

    assert schedule.target(tuesday_midnight)[0] == 20
    assert schedule.target(tuesday_midday)[0] == 20
    assert schedule.target(wednesday_midday)[0] == 22
    assert schedule.target(thursday_midday)[0] == 22
    assert schedule.target(monday_early)[0] == 22
    assert schedule.target(monday_late)[0] == 20
