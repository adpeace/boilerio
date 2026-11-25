from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import Mock

import pytest

from .. import app, model, sensors, zones


@pytest.fixture
def client():
    return app.create_app({'HEATING_TIMEZONE': 'Europe/London',
                           'LOGIN_DISABLED': True, 'SECRET_KEY': 'test'}).test_client()


@pytest.mark.parametrize('endpoint,body', [
    ('/sensor/1/readings', {'metric_type': 'temperature', 'value': 20}),
    ('/zones/1/gradient_measurements', {'delta': 10, 'gradient': 2}),
])
@pytest.mark.parametrize('when', ['2026-07-01T12:00:00', 'bad', None])
def test_api_rejects_naive_or_invalid_timestamps(client, endpoint, body, when):
    response = client.post(endpoint, json={**body, 'when': when}, headers={'X-Requested-With': 'test'})
    assert response.status_code == 400


@pytest.mark.parametrize('endpoint,module,cls,body', [
    ('/sensor/1/readings', sensors, model.SensorReading, {'metric_type': 'temperature', 'value': 20}),
    ('/zones/1/gradient_measurements', zones, model.TemperatureGradientMeasurement, {'delta': 10, 'gradient': 2}),
])
def test_api_normalizes_incoming_offsets(client, monkeypatch, endpoint, module, cls, body):
    monkeypatch.setattr(module, 'get_db', Mock())
    saved = []
    monkeypatch.setattr(cls, 'save', lambda self, db: saved.append(self))
    response = client.post(endpoint, json={**body, 'when': '2026-07-01T12:00:00.123456+01:00'},
                           headers={'X-Requested-With': 'test'})
    assert response.status_code == 200
    assert saved[0].when == datetime.fromisoformat('2026-07-01T11:00:00.123456+00:00')
    assert saved[0].when.utcoffset() == timedelta(0)


@pytest.mark.parametrize('start', [
    '2026-03-29T00:30:15.123456+00:00', '2026-10-25T00:30:15.123456+00:00',
    '2026-03-29T00:30:15+00:00', '2026-10-25T00:30:15+00:00',
])
def test_override_duration_and_both_response_formats(client, monkeypatch, start):
    now = datetime.fromisoformat(start)
    clock = Mock(wraps=zones.datetime)
    clock.datetime.now.return_value = now
    monkeypatch.setattr(zones, 'datetime', clock)
    monkeypatch.setattr(zones, 'get_db', Mock())
    saved = []
    monkeypatch.setattr(model.TargetOverride, 'save', lambda self, db: saved.append(self))
    response = client.post('/zones/1/override', data={'temp': '20', 'hours': '2'},
                           headers={'X-Requested-With': 'test'})
    assert response.status_code == 200
    assert saved[0].end - now == timedelta(hours=2)
    monkeypatch.setattr(model.TargetOverride, 'from_db', lambda *args: saved)
    result = client.get('/zones/1/override')
    assert result.json['end'] == saved[0].to_dict()['until']
    assert result.json['end'] == (now + timedelta(hours=2)).isoformat()


def test_summary_uses_heating_calendar_and_matches_scheduler(client, monkeypatch):
    from datetime import time
    from ...controller import SchedulerTemperaturePolicy
    now = datetime.fromisoformat('2026-07-05T23:30:00+00:00')  # Monday in London, Sunday in UTC.
    schedule = model.FullSchedule([(0, time(0), 1, 20), (6, time(0), 1, 15)])
    clock = Mock(wraps=app.datetime)
    clock.datetime.now.return_value = now
    monkeypatch.setattr(app, 'datetime', clock)
    monkeypatch.setattr(app, 'get_db', Mock())
    monkeypatch.setattr(model.FullSchedule, 'from_db', lambda *args: schedule)
    monkeypatch.setattr(model.Zone, 'all_from_db', lambda *args: [model.Zone(1, 'Room', '0x1', 1)])
    monkeypatch.setattr(model.TargetOverride, 'from_db', lambda *args: [])
    monkeypatch.setattr(model.DeviceState, 'last_from_db', lambda *args: None)
    result = client.get('/summary').json
    policy = SchedulerTemperaturePolicy(schedule, [], ZoneInfo('Europe/London'))
    assert result['server_day_of_week'] == 0
    assert result['zones'][0]['target'] == policy.target(now, 1) == 20
    assert result['today'][0]['zones'][0]['temp'] == 20
