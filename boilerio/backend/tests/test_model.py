from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from .. import model


def test_sensor_from_db_missing_raises():
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    conn = MagicMock()
    conn.cursor.return_value = cursor
    with pytest.raises(ValueError):
        model.Sensor.from_db(conn, 99)


@pytest.mark.parametrize('construct,attribute', [
    (lambda when: model.TargetOverride(when, 20, 1), 'end'),
    (lambda when: model.ControllerState(when, 1, 'heating', 20, 18, None, 10, 1), 'received'),
    (lambda when: model.SensorReading(1, when, 'temperature', 20), 'when'),
    (lambda when: model.TemperatureGradientMeasurement(1, when, 10, 2), 'when'),
])
def test_models_normalize_offsets_and_reject_naive_timestamps(construct, attribute):
    when = datetime.fromisoformat('2026-07-01T12:34:56.123456+01:00')
    normalized = getattr(construct(when), attribute)
    assert normalized == when
    assert normalized.utcoffset() == timedelta(0)
    assert normalized.hour == 11
    assert normalized.microsecond == 123456
    with pytest.raises(ValueError):
        construct(when.replace(tzinfo=None))


def test_never_infer_timezone_for_a_naive_datetime():
    with pytest.raises(ValueError):
        model.as_utc(datetime(2026, 7, 1))


@pytest.mark.parametrize('zone_id', [0, 1, -1])
def test_clear_override_only_deletes_the_requested_zone(zone_id):
    conn = MagicMock()
    model.TargetOverride.clear_from_db(conn, zone_id)
    conn.cursor.return_value.execute.assert_called_once_with(
        'delete from override where zone=%s', (zone_id,))


def test_clear_all_overrides_requires_no_zone_id():
    conn = MagicMock()
    model.TargetOverride.clear_from_db(conn)
    conn.cursor.return_value.execute.assert_called_once_with('delete from override')
