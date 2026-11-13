from datetime import datetime, time, timedelta, timezone
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from .. import app, model, status, zones


NOW = datetime(2026, 7, 5, 23, 30, tzinfo=timezone.utc)  # Monday in London.


@pytest.fixture
def data(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr(zones, 'get_db', lambda: db)
    monkeypatch.setattr(model.Zone, 'all_from_db', lambda db: [
        model.Zone(0, 'Downstairs', 'relay0', 10), model.Zone(2, 'Upstairs', 'relay2', 11)])
    monkeypatch.setattr(model.FullSchedule, 'from_db', lambda db: model.FullSchedule([
        (0, time(0), 0, 20), (6, time(0), 0, 15)]))
    monkeypatch.setattr(model.TargetOverride, 'from_db', lambda db: [])
    db.cursor.return_value.fetchall.return_value = [
        (0, NOW - timedelta(seconds=30), 'On', 18, 17.5, None, 12, 1, False)]
    return db


def test_status_distinguishes_desired_reported_and_missing_reports(data):
    result = status.zone_status(data, ZoneInfo('Europe/London'), now=NOW)
    assert result['as_of'] == NOW
    assert result['schedule_timezone'] == 'Europe/London'
    downstairs, upstairs = result['zones']
    assert downstairs['desired'] == {'target_temperature': 20, 'override': None}
    assert downstairs['reported']['target_temperature'] == 18
    assert downstairs['reported']['override_active'] is False
    assert downstairs['reported']['received_at'] == NOW - timedelta(seconds=30)
    assert upstairs['desired']['target_temperature'] is None
    assert upstairs['reported'] is None
    data.cursor.return_value.execute.assert_called_once()


@pytest.mark.parametrize('remaining,active', [(1, True), (0, False), (-1, False)])
def test_status_override_expires_at_its_utc_deadline(data, monkeypatch, remaining, active):
    override = model.TargetOverride(NOW + timedelta(seconds=remaining), 22, 0)
    monkeypatch.setattr(model.TargetOverride, 'from_db', lambda db: [override])
    desired = status.zone_status(data, ZoneInfo('Europe/London'), now=NOW)['zones'][0]['desired']
    assert desired['target_temperature'] == (22 if active else 20)
    assert (desired['override'] is not None) is active
