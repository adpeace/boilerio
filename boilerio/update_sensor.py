import requests
import logging
import datetime

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class TempSensorUpdater(object):
    def __init__(self, api_url, auth):
        self.api_url = api_url
        self.auth = auth

    def add_sensor(self, sensor):
        sensor.add_callback(self._sensor_callback)

    def _mk_sensor_url(self, sensor):
        return self.api_url + ('/sensor/%d/readings' % sensor.sensor_id)

    def _publish_updated_value(self, url: str, metric_type: str, when: datetime.datetime, value: float) -> None:
        data = {
            'metric_type': metric_type,
            'when': when.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            'value': value,
        }

        r = requests.post(url, json=data, auth=self.auth, headers={'X-Requested-With': 'device'})
        r.raise_for_status()

    def _sensor_callback(self, sensor):
        try:
            sensor_url = self._mk_sensor_url(sensor)
            self._publish_updated_value(
                sensor_url, 'temperature', sensor.reading.when, sensor.reading.temperature)
            self._publish_updated_value(
                sensor_url, 'humidity', sensor.reading.when, sensor.reading.relative_humidity)
        except Exception as e:
            logger.error("Failed to post update for sensor %d: %s",
                         sensor.sensor_id, str(e))
