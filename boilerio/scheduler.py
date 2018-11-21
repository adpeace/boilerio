#!/usr/bin/env python

"""Operate heating schedule."""

import sys
import json
import datetime
import threading
import logging
import paho.mqtt.client as mqtt
import requests
import requests.exceptions
from requests.auth import HTTPBasicAuth

import model
import config

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

strptime = datetime.datetime.strptime
strftime = datetime.datetime.strftime

class ZoneInfoUnavailable(Exception):
    pass

class SchedulerTemperaturePolicy(object):
    ENTRY_TARGET_OVERRIDE = -2

    def __init__(self, schedule, tgt_override):
        self.schedule = schedule
        self.target_override = tgt_override

    @classmethod
    def from_json(cls, j):
        data = json.loads(j)

        entries = []
        for day in sorted(data['schedule']):
            for item in data['schedule'][day]:
                entries.append((
                    int(day),
                    strptime(item['time'], "%H:%M").time(),
                    item['temp']
                    ))
        schedule = model.FullSchedule(entries)
        tgt_override = data['target_override']
        if all(x in tgt_override for x in ['temp', 'until']):
            tgt_override_obj = model.TargetOverride(
                strptime(tgt_override['until'], '%Y-%m-%dT%H:%M'),
                tgt_override['temp'])
        else:
            tgt_override_obj = None
        return cls(schedule, tgt_override_obj)

    def get_day(self, day):
        """Determine the schedule for today covering the full 24h.

        Uses the overall schedule and any schedule overrides (but not
        target tmperature overrides) in place.
        """
        if not self.schedule.entries:
            return []
        entries = []

        # Populate with the day's entries.  Add an entry from the start
        # of the day based on entry prior to that day:
        candidate_beginning = None
        for sday, starttime, temp in self.schedule.entries:
            if sday == day:
                entries.append((starttime, temp))
            elif sday < day:
                candidate_beginning = temp
        if candidate_beginning is None:
            # Wasn't an earlier entry, use the last one in the schedule:
            _, _, temp = self.schedule.entries[-1]
            candidate_beginning = temp
        # Check whether we need to fill in the start:
        if not entries or entries[0][0] != datetime.time(0, 0):
            entries.insert(0, (datetime.time(0, 0), candidate_beginning))

        return entries

    def target(self, now):
        """Determine temperature target at datetime now.

        Returns a pair of (target, index) where index is the number of the
        entry in the day's schedule returned by get_day. Index is -2 if from a
        target override.
        """
        # First check if we are still within an override:
        if self.target_override is not None:
            if self.target_override.end > now:
                return (self.target_override.temp,
                        self.ENTRY_TARGET_OVERRIDE)

        day_schedule = self.get_day(now.weekday())
        now_time = now.time()

        # Iterate over the schedule finding the last entry with a lower time
        # than the requested time.  If we don't find one, we need the last
        # entry from the day before.
        entry = -1
        target = None
        for sched_time, sched_target in day_schedule:
            if sched_time <= now_time:
                target = sched_target
                entry += 1
            else:
                break
        if target is None:
            entry = None
        return target, entry

def mqtt_on_connect(client, userdata, flags, rc):
    if rc:
        logger.error("Error connecting, rc %d", rc)
        return
    for zone in userdata['zones']:
        client.subscribe(zone.sensor)
    client.subscribe(userdata['thermostat_schedule_change_topic'])
    client.subscribe(userdata['thermostat_status_topic'])
    client.subscribe(userdata['temperature_sensor_topic'])

def mqtt_on_message(client, userdata, msg):
    if msg.topic == userdata['thermostat_schedule_change_topic']:
        userdata['timer_event'].set()
    elif msg.topic == userdata['thermostat_status_topic']:
        data = json.loads(msg.payload)
        if 'status' in data and data['status'] == 'online':
            userdata['timer_event'].set()
        if 'mode' in data:
            try:
                now = strftime(datetime.datetime.now(), "%Y-%m-%dT%H:%M:%S")
                r = requests.post(
                    userdata['scheduler_url'] + '/state',
                    auth=userdata['auth'],
                    timeout=10, data={
                        'when': now,
                        'state': data['mode'],
                    })
                logger.info("Cached state update %s, result %d",
                            data['mode'], r.status_code)
            except (requests.exceptions.RequestException, ValueError) as e:
                logger.info("Error updating cached state (%s)",
                            str(e))

def temperature_message(client, userdata, msg):
    data = json.loads(msg.payload)
    if 'temperature' in data:
        # Determine which zone the reading is for:
        sensor_zone = None
        for zone in userdata['zones']:
            if zone.sensor == msg.topic:
                sensor_zone = zone.zone_id
                break
        if sensor_zone is None:
            logger.debug("Received reading for sensor in an unknown zone (%s): ignoring.",
                         msg.topic)
            return
        try:
            temp = float(data['temperature'])
            now = strftime(datetime.datetime.now(), "%Y-%m-%dT%H:%M:%S")
            r = requests.post(
                userdata['scheduler_url'] + '/temperature',
                auth=userdata['auth'],
                timeout=10, data={
                    'when': now,
                    'temp': temp,
                    'zone': sensor_zone
                })
            logger.info("Cached temperature update for zone %d: %.2f, result %d",
                        sensor_zone, temp, r.status_code)
        except (requests.exceptions.RequestException, ValueError) as e:
            logger.info("Error updating cached temperature (%s)",
                        str(e))

def scheduler_iteration(mqttc, target_temp_topic, scheduler_url, auth, now):
    """Fetch schedule, determine target and set it.

    Has no return value and swallows any exceptions fetching the schedule,
    etc., with the intention that a daemon can use this function in a simple
    loop and the correct behaviour will result."""
    try:
        r = requests.get(scheduler_url + "/schedule", auth=auth, timeout=10)
    except requests.exceptions.RequestException as e:
        logger.error("Failed interval (%s)", str(e))
        return

    if r.status_code != 200:
        logger.error("Couldn't get schedule (%d)", r.status_code)
        return

    scheduler = SchedulerTemperaturePolicy.from_json(r.text)
    target = scheduler.target(now)
    if target[0] is None:
        logger.info("No target temperature available.")
    else:
        logger.info("Publishing target temperature update: %d", target[0])
        mqttc.publish(target_temp_topic, json.dumps({'target': target[0]}))

def load_zone_info(scheduler_url, auth):
    """Load zone information from service.

    Try to get zone information.  Cache it to disk under /var/lib/boilerio
    in case we can't get it next time.  Get it from the cached location if
    the HTTP request fails and it is present, otherwise fail (since we don't
    know what zones are present).
    """
    # XXX doesn't do the caching yet :-)
    r = requests.get(scheduler_url + '/zones', auth=auth)
    if r.status_code == 200:
        zones = json.loads(r.text)
        zones = [model.Zone(z['zone_id'], z['name'], z['boiler_relay'], z['sensor'])
                 for z in zones.values()]
        return zones
    raise ZoneInfoUnavailable()

def main():
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

    zones = load_zone_info(scheduler_url, auth)

    period_event = threading.Event()
    mqttc = mqtt.Client(userdata={
        'conf': conf,
        'thermostat_status_topic':
            conf.get('heating', 'thermostat_status_topic'),
        'thermostat_schedule_change_topic':
            conf.get('heating', 'thermostat_schedule_change_topic'),
        'temperature_sensor_topic':
            conf.get('heating', 'temperature_sensor_topic'),
        'timer_event': period_event,
        'scheduler_url': scheduler_url,
        'auth': auth,
        'zones': zones,
        })
    mqttc.username_pw_set(conf.get('mqtt', 'user'),
                          conf.get('mqtt', 'password'))
    mqttc.on_connect = mqtt_on_connect
    mqttc.on_message = mqtt_on_message
    mqttc.connect(conf.get('mqtt', 'host'), 1883, 60)

    # Hook up handlers for temperature sensors:
    for zone in zones:
        mqttc.message_callback_add(zone.sensor, temperature_message)

    mqttc.loop_start()
    while True:
        scheduler_iteration(mqttc, conf.get('heating', 'target_temp_topic'),
                            scheduler_url, auth, datetime.datetime.now())
        period_event.wait(timeout=60)
        period_event.clear()

    mqttc.loop_stop()

if __name__ == "__main__":
    main()
