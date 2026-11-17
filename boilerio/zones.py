from concurrent.futures import Future
from datetime import timedelta
import json
import logging
from queue import Full
import time
import requests

from .background import JobSubmitter
from .cached_resource import CachedResource
from .weather import WeatherReading

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def parse_gradient_table(text):
    table = json.loads(text)
    if not isinstance(table, list) or any(
            not isinstance(row, dict) or
            not all(isinstance(row.get(field), (int, float))
                    for field in ('delta', 'gradient'))
            for row in table):
        raise ValueError('Expected a list of numeric gradient measurements')
    return table


class ZoneController(object):
    """Connect a schedule, thermostat, and temperature sensor."""

    STATE_REPORT_RETRY_INTERVAL = timedelta(minutes=1)

    def __init__(self, zone, boiler, sensor, thermostat_obj, scheduler_url,
                 auth, weather, upload_worker: JobSubmitter,
                 gradient_table_update_frequency=timedelta(hours=1),
                 gradient_table_cache_path=None, fetch_worker=None,
                 clock=time.monotonic):
        """Initialize a zone controller.

        Note that the weather is updated on each iteration so the weather
        object needs to do caching to avoid frequent API calls."""
        self.zone = zone
        self._last_reported_state = None
        self._pending_report = None
        self._upload_worker = upload_worker
        self.clock = clock
        self.boiler = boiler
        self.thermostat = thermostat_obj
        self.thermostat.set_state_change_callback(self.thermostat_state_callback)
        self._sensor = sensor
        self.scheduler_url = scheduler_url
        self.scheduler_auth = auth

        self.reported_state = {
                'time_to_target': None,
                'state': 'Unknown',
                'target': None,
                'current_temp': None,
                'current_outside_temp': None,
                'dutycycle': None,
                'target_overridden': None,
                }
        # Only the control thread updates reporting state and upload acknowledgments.
        self._next_state_report_attempt = None
        self.gradient_table = []
        self._gradient_resource = CachedResource(
            scheduler_url + '/zones/%d/gradients' % zone.zone_id, parse_gradient_table,
            auth=auth, cache_path=gradient_table_cache_path,
            update_interval=gradient_table_update_frequency, worker=fetch_worker, clock=clock)
        self.weather = weather

    def thermostat_state_callback(self, new_state, dutycycle):
        self._update_state(state=new_state, dutycycle=dutycycle)

    def _update_state(self, **kwargs):
        """Update fields in the zone's reported state."""
        new_state = self.reported_state.copy()
        new_state.update(**kwargs)
        if new_state != self.reported_state:
            self.reported_state = new_state
            logger.debug("State change: %s", str(kwargs))

    def _should_report_state(self, tick: float) -> bool:
        """Return whether changed state is eligible for upload at tick."""
        return (self.reported_state != self._last_reported_state and
                (self._next_state_report_attempt is None or tick >= self._next_state_report_attempt))

    def get_time_to_target(self, outside: WeatherReading | None) -> timedelta | None:
        """Return the estimated time to reach the target temperature, or None."""
        # This algorithm overestimates the time taken because it uses the
        # gradient at the start of heating, whereas it should be using an
        # integral over time.

        # If we're not heating, just return nothing:
        if (outside is None or not self.thermostat.is_heating or
            self._sensor.reading is None or
            self.thermostat.target < self._sensor.reading.temperature):
            return None
        else:
            delta_t = self._sensor.reading.temperature - outside.temperature

            # Find a gradient where the delta between inside and out was
            # closest to the current temperature:
            match = None
            for gradient in self.gradient_table:
                if match is None:
                    match = gradient
                elif (abs(gradient['delta'] - delta_t)
                        < abs(match['delta'] - delta_t)):
                    match = gradient

            # Now use it to estimate heating time:
            if match is None:
                return None
            amount_to_heat = self.thermostat.target - self._sensor.reading.temperature
            return timedelta(hours=(amount_to_heat / match['gradient']))

    def report_updated_state(self, tick: float) -> None:
        """Process pending upload results and report changed zone state."""
        if self._pending_report is not None:
            state, result = self._pending_report
            if not result.done():
                return
            self._pending_report = None
            success, completed_at = result.result()
            self._record_report_result(state, success, completed_at)

        if not self._should_report_state(tick):
            return
        state = self.reported_state.copy()
        result = Future()

        def upload():
            success = False
            try:
                success = self._post_state(state)
            finally:
                # Publish completion without modifying controller state.
                result.set_result((success, self.clock()))

        try:
            self._upload_worker.submit(self, upload)
        except Full:
            logger.warning('Zone state upload queue full for zone %d', self.zone.zone_id)
        else:
            self._pending_report = (state, result)

    def _record_report_result(self, state, success: bool, completed_at: float) -> None:
        if success:
            self._last_reported_state = state
            self._next_state_report_attempt = None
        else:
            self._next_state_report_attempt = completed_at + self.STATE_REPORT_RETRY_INTERVAL.total_seconds()

    def _post_state(self, state) -> bool:
        url = self.scheduler_url + '/zones/%d/reported_state' % self.zone.zone_id
        try:
            r = requests.post(url, auth=self.scheduler_auth,
                timeout=10, json=state, headers={'X-Requested-With': 'device'})
        except requests.exceptions.RequestException as e:
            logger.error("Couldn't update state (zone %d, url %s): %s",
                         self.zone.zone_id, url, type(e).__name__)
            return False
        if r.status_code == 200:
            logger.info("Reported new state for zone %d: %s",
                    self.zone.zone_id, state)
            return True
        else:
            logger.error("Couldn't update state (zone %d, url %s, data %s)",
                    self.zone.zone_id, url, state)
            return False

    def iteration(self, scheduler, now, tick, fetch_deadline: float | None = None):
        """Update zone control and reports, waiting for fresh data until fetch_deadline."""
        # Update target temperature by polling scheduler
        target = scheduler.target(now, self.zone.zone_id)
        reading = self._sensor.reading
        self._update_state(
            current_temp=reading.temperature if reading is not None else None,
            target_overridden=scheduler.target_overridden(now,
                                                          self.zone.zone_id))
        if self.thermostat.target != target:
            logger.info("Updating target temperature (%s -> %s) for zone %d",
                        str(self.thermostat.target), str(target), self.zone.zone_id)
            self.thermostat.set_target_temperature(target)
            self._update_state(target=target)

        # Update gradient table:
        table = self._gradient_resource.get(fetch_deadline)
        if table is not None:
            self.gradient_table = table

        # Update thermostat:
        self.thermostat.interval_elapsed(tick)

        # Update weather:
        current_weather = self.weather.get_weather(fetch_deadline)
        time_to_target = self.get_time_to_target(current_weather)
        self._update_state(
            current_outside_temp=(current_weather.temperature
                                  if current_weather is not None else None),
            time_to_target=(time_to_target.total_seconds()
                            if time_to_target is not None else None))

        # Collect upload results even if local state has reverted to its last acknowledgment.
        self.report_updated_state(tick)
