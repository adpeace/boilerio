#!/usr/bin/env python

import datetime
import logging
import argparse
import json
import time

import paho.mqtt.client as mqtt

import config
from thermostat import Thermostat, TempReading

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class MqttBoiler(object):
    """Control boiler using MQTT commands."""
    # Time after which we might re-issue the same command to the boiler
    REISSUE_TIMEOUT = datetime.timedelta(0, 120)

    def __init__(self, thermostat_id, mqttc, zone_demand_topic):
        self.mqttc = mqttc
        self.zone_demand_topic = zone_demand_topic
        self.last_cmd = None
        self.last_cmd_time = None
        self.thermostat_id = thermostat_id

    def _command(self, cmd):
        now = datetime.datetime.now()
        if cmd != self.last_cmd or \
           self.last_cmd_time < now - self.REISSUE_TIMEOUT:
            logger.debug("Issuing boiler command %s", cmd)
            self.mqttc.publish(self.zone_demand_topic, json.dumps({
                'thermostat': self.thermostat_id,
                'command': cmd}))
            self.last_cmd = cmd
            self.last_cmd_time = now

    def on(self):
        self._command('O')

    def off(self):
        self._command('X')

# Temperature reading update:
def on_connect(client, userdata, flags, rc):
    if rc:
        logger.error("Error connecting, rc %d", rc)
        return
    client.subscribe(userdata['tempsensor'])
    client.subscribe(userdata['target_temp'])
    client.publish(userdata['thermostat_status_topic'], json.dumps({
        'thermostat_id': userdata['thermostat_id'],
        'status': 'online'}))

def on_message(client, userdata, msg):
    thermostat = userdata['thermostat']

    def temperature_update():
        data = json.loads(msg.payload)
        if 'temperature' not in data:
            return

        try:
            temp = float(data['temperature'])
        except ValueError:
            return

        now = datetime.datetime.now()
        thermostat.update_temperature(TempReading(now, temp))

    def target_update():
        # Payload should be dictionary with key 'target':
        try:
            target = float(json.loads(msg.payload)['target'])
            thermostat.set_target_temperature(target)
        except (KeyError, ValueError):
            pass

    if msg.topic == userdata['tempsensor']:
        temperature_update()
    elif msg.topic == userdata['target_temp']:
        target_update()

class StateCallback(object):
    def __init__(self, mqttc, status_topic):
        self.mqttc = mqttc
        self.status_topic = status_topic

    def callback(self, mode):
        self.mqttc.publish(self.status_topic, json.dumps(
            {'mode': mode}))

def maintain_temp(sensor_topic, thermostat_id, dry_run):
    conf = config.load_config()
    mqttc = mqtt.Client()
    boiler_control = MqttBoiler(
        thermostat_id, mqttc, conf.get('heating', 'demand_request_topic'))
    state_callback = StateCallback(mqttc, conf.get(
        'heating', 'thermostat_status_topic'))

    thermostat = Thermostat(boiler_control, state_callback.callback)
    mqttc.user_data_set({
        'thermostat': thermostat,
        'tempsensor': sensor_topic,
        'target_temp': conf.get('heating', 'target_temp_topic'),
        'thermostat_status_topic': conf.get('heating',
                                            'thermostat_status_topic'),
        'thermostat_id': thermostat_id,
        })
    mqttc.on_connect = on_connect
    mqttc.on_message = on_message
    mqttc.username_pw_set(conf.get('mqtt', 'user'),
                          conf.get('mqtt', 'password'))
    mqttc.will_set(
        conf.get('heating', 'thermostat_status_topic'),
        json.dumps({'thermostat_id': thermostat_id, 'status': 'offline'}))
    mqttc.connect(conf.get('mqtt', 'host'), 1883, 60)

    mqttc.loop_start()
    while True:
        time.sleep(1)
        now = datetime.datetime.now()
        thermostat.interval_elapsed(now)

def main():
    parser = argparse.ArgumentParser(description="Maintain target temperature")
    parser.add_argument("-n", action="store_true", dest="dry_run")
    parser.add_argument("sensor_topic")
    parser.add_argument("thermostat_id")
    args = parser.parse_args()

    maintain_temp(args.sensor_topic, int(args.thermostat_id, 0), args.dry_run)

if __name__ == "__main__":
    main()
