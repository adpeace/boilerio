import requests
import logging

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

    def _sensor_callback(self, sensor):
        try:
            sensor_url = self._mk_sensor_url(sensor)
            data = {
                'metric_type': 'temperature',
                'when': sensor.temperature.when.strftime(
                    "%Y-%m-%dT%H:%M:%S.%fZ"),
                'value': sensor.temperature.reading,
            }

            r = requests.post(sensor_url, json=data, auth=self.auth)
            r.raise_for_status()
        except Exception as e:
            logger.error("Failed to post update for sensor %d: %s",
                         sensor.sensor_id, str(e))
