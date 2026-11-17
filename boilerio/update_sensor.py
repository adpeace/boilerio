import requests
import logging
import datetime
from queue import Full

from .background import JobSubmitter

REPORT_INTERVAL_SECONDS = 15 * 60

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class TempSensorUpdater(object):
    def __init__(self, api_url, auth, worker: JobSubmitter):
        self.api_url = api_url
        self.auth = auth
        self._last_reports = {}
        self._worker = worker

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

        r = requests.post(url, json=data, auth=self.auth, timeout=10,
                          headers={'X-Requested-With': 'device'})
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
            url = self._mk_sensor_url(sensor)

            def upload(key=key, value=value, when=reading.when,
                       received_at=reading.received_at, url=url):
                self._upload_metric(key, value, when, received_at, url)

            try:
                self._worker.submit((self, key), upload)
            except Full:
                logger.warning('Sensor upload deferred until next report: %s', key)

    def _upload_metric(self, key, value, when, received_at, url):
        previous = self._last_reports.get(key)
        if (previous is not None and previous[0] == value and
                received_at - previous[1] < REPORT_INTERVAL_SECONDS):
            return
        try:
            self._publish_updated_value(url, key[1], when, value)
            # Failed uploads can retry on the next actual MQTT report.
            self._last_reports[key] = (value, received_at)
        except Exception as e:
            logger.error('Failed to post %s update for sensor %d: %s', key[1], key[0], e)
