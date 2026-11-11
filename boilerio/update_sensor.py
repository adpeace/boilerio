import requests
import logging
import datetime

REPORT_INTERVAL_SECONDS = 15 * 60

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class TempSensorUpdater(object):
    def __init__(self, api_url, auth):
        self.api_url = api_url
        self.auth = auth
        self._last_reports = {}

    def add_sensor(self, sensor):
        sensor.add_callback(self._sensor_callback)

    def _mk_sensor_url(self, sensor):
        return self.api_url + ('/sensor/%d/readings' % sensor.sensor_id)

    def _publish_updated_value(self, url: str, metric_type: str, when: datetime.datetime, value: float) -> None:
        data = {
            'metric_type': metric_type,
            'when': when.isoformat(),
            'value': value,
        }

        r = requests.post(url, json=data, auth=self.auth, headers={'X-Requested-With': 'device'})
        r.raise_for_status()

    def _sensor_callback(self, sensor):
        reading = sensor.reading
        for metric_type, value in (
                ('temperature', reading.temperature),
                ('humidity', reading.relative_humidity),
                ('battery_voltage', reading.battery_voltage)):
            if value is None:
                continue
            key = (sensor.sensor_id, metric_type)
            previous = self._last_reports.get(key)
            if (previous is not None and previous[0] == value and
                    reading.received_at - previous[1] < REPORT_INTERVAL_SECONDS):
                continue
            try:
                self._publish_updated_value(
                    self._mk_sensor_url(sensor), metric_type, reading.when, value)
                # Failed uploads can retry on the next MQTT report.
                self._last_reports[key] = (value, reading.received_at)
            except Exception as e:
                logger.error("Failed to post %s update for sensor %d: %s",
                             metric_type, sensor.sensor_id, str(e))
