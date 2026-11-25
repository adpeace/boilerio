"""Startup configuration parsing, validation, and cache recovery."""

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import time
from zoneinfo import ZoneInfo

from .cached_resource import FetchRequest, fetch_startup, write_backup, log_backup_file_age
from .backend.model import Zone
from .tempsensor import EmonTHSensor

logger = logging.getLogger(__name__)


def parse_timezone(data) -> ZoneInfo:
    return ZoneInfo(data['timezone'])


def parse_sensors(data) -> dict[int, EmonTHSensor]:
    if not isinstance(data, list):
        raise ValueError('Expected a list of sensors')
    sensors = {}
    for item in data:
        sensor_id, locator = item['sensor_id'], item['locator']
        if type(sensor_id) is not int or not isinstance(locator, str) or not locator:
            raise ValueError('Expected sensor ID and MQTT topic')
        if sensor_id in sensors:
            raise ValueError('Duplicate sensor ID')
        sensors[sensor_id] = EmonTHSensor(sensor_id, locator)
    return sensors


def parse_zones(data) -> list[Zone]:
    if not isinstance(data, list):
        raise ValueError('Expected a list of zones')
    zones = []
    ids = set()
    for item in data:
        zone_id, sensor_id = item['zone_id'], item['sensor_id']
        relay, name = item['boiler_relay'], item['name']
        if (type(zone_id) is not int or type(sensor_id) is not int or
                not isinstance(name, str) or not isinstance(relay, str)):
            raise ValueError('Expected zone IDs, name, and relay address')
        int(relay, 0)
        if zone_id in ids:
            raise ValueError('Duplicate zone ID')
        ids.add(zone_id)
        zones.append(Zone(zone_id, name, relay, sensor_id))
    return zones


@dataclass
class Configuration:
    """The heating timezone, configured sensors, and compatible heating zones."""

    timezone: ZoneInfo
    sensors: dict[int, EmonTHSensor]
    zones: list[Zone]

    def __post_init__(self) -> None:
        for zone in self.zones:
            if zone.sensor_id not in self.sensors:
                raise ValueError(f'Zone {zone.zone_id} references an unavailable sensor {zone.sensor_id}')

    @classmethod
    def from_json(cls, text: str) -> 'Configuration':
        """Parse a complete configuration snapshot, rejecting invalid data."""
        data = json.loads(text)
        return cls(parse_timezone(data['system']), parse_sensors(data['sensors']),
                   parse_zones(data['zones']))

    def to_json(self) -> str:
        """Serialize the configuration as a complete startup snapshot."""
        return json.dumps({
            'system': {'timezone': self.timezone.key},
            'sensors': [{'sensor_id': sensor.sensor_id, 'locator': sensor.locator}
                        for sensor in self.sensors.values()],
            'zones': [{'zone_id': zone.zone_id, 'name': zone.name,
                       'boiler_relay': zone.boiler_relay, 'sensor_id': zone.sensor_id}
                      for zone in self.zones],
        })


def load_configuration(url, auth, deadline, cache_path, clock=time.monotonic) -> Configuration:
    """Load a complete online configuration, falling back to the saved snapshot.

    Save successful refreshes atomically. Ignore partial or invalid refreshes
    and leave the snapshot unchanged. Raise ValueError if neither source is valid.
    """
    cache_path = Path(cache_path)
    fetch_requests = {
        'timezone': FetchRequest(url + '/system', lambda text: parse_timezone(json.loads(text)), auth=auth),
        'sensors': FetchRequest(url + '/sensor/', lambda text: parse_sensors(json.loads(text)), auth=auth),
        'zones': FetchRequest(url + '/zones', lambda text: parse_zones(json.loads(text)), auth=auth),
    }
    results = fetch_startup(fetch_requests, deadline, clock)
    fresh = {name: result.value for name, result in results.items() if result.success}
    if len(fresh) == len(fetch_requests):
        try:
            configuration = Configuration(**fresh)
        except ValueError as error:
            logger.warning('Online configuration is incompatible: %s', error)
        else:
            write_backup(cache_path, configuration.to_json())
            return configuration

    try:
        configuration = Configuration.from_json(cache_path.read_text())
    except (OSError, ValueError, KeyError, TypeError) as error:
        logger.warning("Couldn't load configuration snapshot %s: %s", cache_path, error)
    else:
        log_backup_file_age(cache_path)
        return configuration
    raise ValueError('No valid startup configuration available from server or cache')
