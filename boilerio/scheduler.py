#!/usr/bin/env python

"""Operate heating schedule."""

import sys
import json
import datetime
from datetime import timedelta
import logging
import time
import math
from pathlib import Path

import paho.mqtt.client as mqtt
from requests.auth import HTTPBasicAuth

from .schedulerweb import model # XXX
from . import config
from . import thermostat
from . import update_sensor
from . import weather
from . import zones
from . import startup
from .background import WorkerPool
from .cached_resource import CachedResource, refresh_startup
from .version import software_version

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

strptime = datetime.datetime.strptime
strftime = datetime.datetime.strftime

class MqttBoiler(object):
    """Control boiler using MQTT commands."""
    # Time after which we might re-issue the same command to the boiler
    REISSUE_TIMEOUT = timedelta(0, 120)

    def __init__(self, thermostat_id, mqttc, zone_demand_topic):
        self.mqttc = mqttc
        self.zone_demand_topic = zone_demand_topic
        self.last_cmd = None
        self.last_cmd_time = None
        self.thermostat_id = thermostat_id

    def _command(self, cmd):
        now = time.monotonic()
        if cmd != self.last_cmd or \
           self.last_cmd_time < now - self.REISSUE_TIMEOUT.total_seconds():
            logger.debug("Issuing boiler command %s for relay %s", cmd, self.thermostat_id)
            self.mqttc.publish(self.zone_demand_topic, json.dumps({
                'thermostat': self.thermostat_id,
                'command': cmd}))
            self.last_cmd = cmd
            self.last_cmd_time = now

    def on(self):
        self._command('O')

    def off(self):
        self._command('X')

class SchedulerTemperaturePolicy(object):
    ENTRY_TARGET_OVERRIDE = -2

    def __init__(self, schedule, tgt_override, heating_timezone):
        """Initialise policy object from FullSchedule and override.

        Note that FullSchedule is basically a wrapper around a list but
        requires that the entries are sorted by day then time then zone.
        """
        self.heating_timezone = heating_timezone
        self.schedule = schedule
        self.target_override = tgt_override

    @classmethod
    def from_json(cls, j, heating_timezone):
        data = json.loads(j)

        def temperature(value):
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                raise ValueError('Expected a finite temperature or null')
            return value

        entries = []
        for day in sorted(data['schedule']):
            for item in data['schedule'][day]:
                for zone in item['zones']:
                    entries.append((
                        int(day),
                        strptime(item['when'], "%H:%M").time(),
                        zone['zone'],
                        temperature(zone['temp'])
                        ))
        schedule = model.FullSchedule(entries)
        tgt_override = data['target_override']
        tgt_override = [
            model.TargetOverride(datetime.datetime.fromisoformat(t['until']),
                                 temperature(t['temp']), t['zone'])
            for t in tgt_override
            ]
        return cls(schedule, tgt_override, heating_timezone)

    def get_day(self, day, zone):
        """Determine the schedule for today covering the full 24h.

        Uses the overall schedule and any schedule overrides (but not
        target tmperature overrides) in place.

        Returns a list of the form:
            [ (starttime, zone, temperature) ]
        """
        sched_for_zone = [e for e in self.schedule.entries
                          if e[2] == zone]
        if not sched_for_zone:
            return []

        entries = []

        # Populate with the day's entries.  Add an entry from the start
        # of the day based on entry prior to that day:
        candidate_beginning = None
        for sday, starttime, entry_zone, temp in sched_for_zone:
            if entry_zone != zone:
                continue
            if sday == day:
                entries.append((starttime, zone, temp))
            elif sday < day:
                candidate_beginning = temp
        if candidate_beginning is None:
            # Wasn't an earlier entry, use the last one in the schedule:
            _, _, _, temp = sched_for_zone[-1]
            candidate_beginning = temp
        # Check whether we need to fill in the start:
        if not entries or entries[0][0] != datetime.time(0, 0):
            entries.insert(0, (datetime.time(0, 0), zone, candidate_beginning))

        return entries

    def target_overridden(self, now, zone):
        if self.target_override is not None:
            return any(t.zone == zone and t.end > now
                       for t in self.target_override)
        return False

    def target(self, now, zone):
        """Determine temperature target at datetime now."""
        # First check if we are still within an override:
        if self.target_override is not None:
            for override in self.target_override:
                if override.zone == zone and override.end > now:
                    return override.temp

        local_now = now.astimezone(self.heating_timezone)
        day_schedule = self.get_day(local_now.weekday(), zone)
        now_time = local_now.time()

        # Iterate over the schedule finding the last entry with a lower time
        # than the requested time.  If we don't find one, we need the last
        # entry from the day before.
        target = None
        for sched_time, _, sched_target in day_schedule:
            if sched_time <= now_time:
                target = sched_target
            else:
                break
        return target

def mqtt_on_connect(client, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        logger.error("Error connecting to MQTT: %s", reason_code)
        return
    for sensor in userdata['sensors'].values():
        client.subscribe(sensor.locator)
    client.subscribe(userdata['thermostat_schedule_change_topic'])

class AllZoneController(object):
    """Controller for multiple zones.

    Interfaces between the web API and a set of local zone controllers."""

    SCHEDULER_UPDATE_INTERVAL = timedelta(seconds=60)
    FETCH_WAIT_SECONDS = 5

    def __init__(self, scheduler_url, auth, zone_controllers, heating_timezone,
                 schedule_cache_path=None, fetch_worker=None, clock=time.monotonic):
        self.clock = clock
        self.heating_timezone = heating_timezone
        self.scheduler = None
        self._schedule_resource = CachedResource(
            scheduler_url + '/schedule',
            lambda text: SchedulerTemperaturePolicy.from_json(text, heating_timezone),
            auth=auth, cache_path=schedule_cache_path,
            update_interval=self.SCHEDULER_UPDATE_INTERVAL, worker=fetch_worker, clock=clock)

        self.scheduler_url = scheduler_url
        self.auth = auth
        self.zone_controllers = zone_controllers

    def iteration(self, now: datetime.datetime, tick: float) -> None:
        """Perform one iteration of the control loop

        :param datetime now: The current wall-clock time.
        :param float tick: Monotonic time in seconds."""
        fetch_deadline = self.clock() + self.FETCH_WAIT_SECONDS
        self.scheduler = self._schedule_resource.get(fetch_deadline)

        # Update thermostats:
        if self.scheduler:
            for controller in self.zone_controllers:
                controller.iteration(self.scheduler, now, tick, fetch_deadline)


def build_controller(conf, scheduler_url, auth, mqttc, fetch_worker, upload_worker,
                     cache_dir=Path('/var/lib/boilerio'), startup_timeout=30, clock=time.monotonic):
    """Return a multi-zone controller and its sensors after loading startup data."""
    # Complete bounded startup refreshes before the control loop starts using cached data.
    deadline = clock() + startup_timeout
    cache_dir = Path(cache_dir)
    weather_obj = weather.Weather(conf.get('weather', 'apikey'),
                                  conf.get('weather', 'location'),
                                  cache_time=timedelta(minutes=20), worker=fetch_worker, clock=clock)
    configuration = startup.load_configuration(
        scheduler_url, auth, min(deadline, clock() + 10), cache_dir / 'configuration', clock=clock)
    sensor_updater = update_sensor.TempSensorUpdater(scheduler_url, auth, upload_worker)
    for sensor in configuration.sensors.values():
        sensor.register_mqtt_callbacks(mqttc)
        sensor_updater.add_sensor(sensor)

    controllers = []
    for zone in configuration.zones:
        boiler = MqttBoiler(zone.boiler_relay, mqttc,
                            conf.get('heating', 'demand_request_topic'))
        sensor = configuration.sensors[zone.sensor_id]
        controller = zones.ZoneController(
            zone, boiler, sensor, thermostat.Thermostat(boiler, sensor),
            scheduler_url, auth, weather_obj,
            gradient_table_cache_path=cache_dir / f'gradients-{zone.zone_id}',
            fetch_worker=fetch_worker, upload_worker=upload_worker, clock=clock)
        controllers.append(controller)

    controller = AllZoneController(
        scheduler_url, auth, controllers, configuration.timezone,
        schedule_cache_path=cache_dir / 'schedule', fetch_worker=fetch_worker, clock=clock)
    refresh_startup([controller._schedule_resource] + [
        zone._gradient_resource for zone in controllers] + [weather_obj._resource], deadline, clock)
    return controller, configuration.sensors

def main():
    logger.info("Starting boilerio scheduler %s", software_version())
    conf = config.load_config()

    # If the 'heating' section of the config has a 'scheduler_username' and
    # 'scheduler_password' entry, we use these with HTTP basic auth.
    if conf.has_option('heating', 'scheduler_username') and \
       conf.has_option('heating', 'scheduler_password'):
        logger.info("Using HTTP basic authentication")
        auth = HTTPBasicAuth(conf.get('heating', 'scheduler_username'),
                             conf.get('heating', 'scheduler_password'))
    else:
        logger.info("Not using HTTP authentication")
        auth = None

    if len(sys.argv) == 2:
        scheduler_url = sys.argv[1]
    else:
        scheduler_url = conf.get('heating', 'scheduler_url')

    userdata = {
        'conf': conf,
        'thermostat_schedule_change_topic':
            conf.get('heating', 'thermostat_schedule_change_topic'),
        'scheduler_url': scheduler_url,
        'auth': auth,
        'sensors': {},
        }
    mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, userdata=userdata)
    mqttc.username_pw_set(conf.get('mqtt', 'user'),
                          conf.get('mqtt', 'password'))
    mqttc.on_connect = mqtt_on_connect
    fetch_worker = WorkerPool(name='fetch')
    upload_worker = WorkerPool(name='upload')
    try:
        controller, sensors = build_controller(
            conf, scheduler_url, auth, mqttc, fetch_worker, upload_worker)
        userdata['sensors'] = sensors
        mqttc.connect(conf.get('mqtt', 'host'), 1883, 60)
        mqttc.loop_start()
        try:
            while True:
                controller.iteration(datetime.datetime.now(datetime.timezone.utc), time.monotonic())
                time.sleep(1)
        finally:
            mqttc.loop_stop()
    finally:
        fetch_worker.close()
        upload_worker.close()

if __name__ == "__main__":
    main()
