"""Zone status independent of the legacy summary's presentation format."""

from datetime import datetime, timezone

from ..scheduler import SchedulerTemperaturePolicy
from . import model


def zone_status(db, heating_timezone, zone_id=None, now=None):
    """Separate configured intent from the controller's last observation.

    A report receipt time is not a heartbeat. Old reports remain visible and
    their age must not be presented as proof of current device availability.
    """
    now = model.as_utc(now) if now is not None else datetime.now(timezone.utc)
    zones = sorted(model.Zone.all_from_db(db), key=lambda zone: zone.zone_id)
    if zone_id is not None:
        zones = [zone for zone in zones if zone.zone_id == zone_id]
        if not zones:
            return None
    schedule = model.FullSchedule.from_db(db)
    overrides = model.TargetOverride.from_db(db)
    policy = SchedulerTemperaturePolicy(schedule, overrides, heating_timezone)
    active_overrides = {override.zone: override for override in overrides if override.end > now}
    reports = model.DeviceState.latest_for_zones(db, [zone.zone_id for zone in zones])
    result = []
    for zone in zones:
        override = active_overrides.get(zone.zone_id)
        report = reports.get(zone.zone_id)
        result.append({
            'zone_id': zone.zone_id,
            'name': zone.name,
            'sensor_id': zone.sensor_id,
            'desired': {
                'target_temperature': policy.target(now, zone.zone_id),
                'override': {'temperature': override.temp, 'expires_at': override.end}
                if override is not None else None,
            },
            'reported': {
                'received_at': report.received,
                'target_temperature': report.target,
                'current_temperature': report.current_temp,
                'current_outside_temperature': report.current_outside_temp,
                'controller_state': report.state,
                'duty_cycle': report.dutycycle,
                'time_to_target': report.time_to_target,
                'override_active': report.target_overridden,
            } if report is not None else None,
        })
    return {'as_of': now, 'schedule_timezone': heating_timezone.key, 'zones': result}
