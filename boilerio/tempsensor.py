import json
import datetime
import logging
import math
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
    battery_voltage: float | None = None

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
        except Exception:
            logger.critical("Exception escaped from MQTT handler for %s",
                            str(self), exc_info=True)
            return

        voltage = None
        if 'battery' in data:
            try:
                voltage = float(data['battery'])
                if not math.isfinite(voltage) or voltage < 0:
                    raise ValueError("Invalid battery voltage")
            except (ValueError, TypeError, OverflowError):
                logger.warning("Ignoring invalid battery voltage for %s", self.locator)
                voltage = None

        # Refresh local readings on every report. The updater decides which
        # values need uploading and when unchanged readings need re-reporting.
        self.reading = SensorReading(datetime.datetime.now(datetime.timezone.utc),
                                     temp, rh, time.monotonic(), voltage)
        logger.debug("Sensor update: %s", str(self.reading))
        for cb in self._callbacks:
            try:
                cb(self)
            except Exception as e:
                logger.error("Callback %s raised exception %s", cb, e, exc_info=e)
