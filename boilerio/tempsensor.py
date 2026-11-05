import json
import datetime
import logging
import time
from dataclasses import dataclass

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

@dataclass
class SensorReading(object):
    when: datetime.datetime
    temperature: float
    relative_humidity: float
    received_at: float  # Process-local monotonic seconds, never sent over the API.

    def __str__(self):
        return "<SensorReading: %f deg C %f RH at %s>" % (self.temperature, self.relative_humidity, self.when)


class EmonTHSensor(object):
    """A temperature sensor from OpenEnergyMonitor."""

    def __init__(self, sensor_id, locator):
        self.reading = None
        self.sensor_id = sensor_id
        self.locator = locator
        self._callbacks = []

    def register_mqtt_callbacks(self, mqttc):
        logger.debug("Registering callback for %d at %s" %
                     (self.sensor_id, self.locator))
        mqttc.message_callback_add(self.locator, self._temp_callback)

    def add_callback(self, cb):
        self._callbacks.append(cb)

    def _temp_callback(self, client, userdata, msg):
        """Handle MQTT message from emon."""
        try:
            if self.locator != msg.topic:
                return

            data = json.loads(msg.payload)
            if 'temperature' not in data:
                return

            temp = float(data['temperature'])
            rh = float(data['humidity'])

            previous = self.reading
            self.reading = SensorReading(datetime.datetime.now(), temp, rh, time.monotonic())
            # Receipt refreshes freshness even when values have not changed.
            if previous and temp == previous.temperature and rh == previous.relative_humidity:
                return
        except Exception:
            logger.critical("Exception escaped from MQTT handler for %s",
                            str(self), exc_info=True)

        # Call callbacks, making sure any escaping exceptions don't cause
        # subsequent callbacks to fail:
        logger.debug("Temperature update: %s", str(self.reading))
        for cb in self._callbacks:
            try:
                cb(self)
            except Exception as e:
                logger.error("Callback %s raised exception %s", cb, e, exc_info=e)
