# BoilerIO Setup Guide

This guide takes you through setting up the BoilerIO software thermostat.

> [!WARNING]
> No warranty is provided. You are changing how your heating is controlled:
> keep your existing thermostat to hand so you can re-pair it if you need to.

## 1. Overview

![BoilerIO architecture: the web UI, Home Assistant and Alexa use the backend API; the controller on a Raspberry Pi syncs with it, reads sensor readings from an MQTT broker (published by emonhub on a separate sensor hub) and sends boiler control through the Danfoss bridge and JeeLink to the Danfoss receiver](arch-landscape.svg)

The sensor side shows one example setup (emonTH sensors and emonhub); any
sensor that publishes in the right format works (section 5).

BoilerIO is split into several components that talk to each other over MQTT and
HTTPS:

| Component | Runs | Does |
| --- | --- | --- |
| **Backend** (`boilerio.backend`) | On a server, local or in the cloud | Stores schedules, zones, sensors and readings, and serves the REST API used by everything else. |
| **Controller** (`boilerio-controller`) | On-site, e.g. a Raspberry Pi | Fetches the schedule from the backend, reads temperature sensors over MQTT, and controls the boiler accordingly. |
| **Danfoss bridge** (`boilerio-danfoss-bridge`) | On-site with the JeeLink flashed with appropriate firmware | Bridges boiler on/off requests from MQTT to the actual RF protocol |
| **MQTT broker** | On-site | Communication broker for the components. You provide this, e.g. Mosquitto. |
| **Temperature sensors** | On-site, at least one per zone | Publish readings to MQTT as input to the controller. |

The controller and Danfoss bridge ship as one container image, published with each
[GitHub release](https://github.com/adpeace/boilerio/releases).

Once the core system is running, you can add ways to control it:
- [Web UI](https://github.com/adpeace/boilerio-ui)
- [Home Assistant integration](https://github.com/adpeace/boilerio-home-assistant)
- [Alexa skill](https://github.com/adpeace/boilerio-alexa)

## 2. Hardware

- Controller: **A Raspberry Pi (or similar) running a 64-bit OS.** The container
  image is built for `linux/arm64` only. A Pi 3 or later with 64-bit Raspberry
  Pi OS Lite is enough. It needs Docker Engine with the Compose plugin: follow
  Docker's [instructions for
  Debian](https://docs.docker.com/engine/install/debian/), which also apply to
  64-bit Raspberry Pi OS. The commands in this guide assume your user can run
  `docker` (enable this by adding it to the `docker` group with `sudo usermod
  -aG docker $USER` then log out and back in).
- Bridge: **A 433MHz
  [JeeLink](https://www.digitalsmarties.net/products/jeelink)** with an RFM69
  radio (the JeeLink v3c). You can also use other ATmega328P-based
  Arduino-compatible hardware with a 433MHz RFM69CW or RFM69W module on the
  default SPI select pin (D10). Older JeeLinks with an RFM12B radio don't work,
  and nor do high-power RFM69HCW modules: the firmware uses the radio's default
  low-power transmitter, which those modules don't connect to the antenna.
- **A Danfoss RF receiver** such as the RX1 or RX2. These are normally paired
  with the TPx000 series of wireless room thermostats.
- **At least one temperature sensor per zone** that can publish to MQTT. This
  guide uses the
  [emonTH](https://docs.openenergymonitor.org/emonth2/install.html); other
  sensors work with a small bridge (see section 5).
- **Something to host the backend.** This can be the same Pi or a separate
  machine such as an EC2 instance or similar (has to be reachable from the
  controller, but not necessarily the other way around; see section 6).

## 3. Flash the JeeLink

Follow the steps in the thermostat repository's
[README](https://github.com/adpeace/thermostat#flashing).

## 4. MQTT broker

BoilerIO needs an MQTT broker on port 1883 that the Pi can reach. Use an
existing one, or run Mosquitto alongside BoilerIO (see the example below).

### What BoilerIO expects from the broker

- **Authentication.** Recommended: disable anonymous access. Give each client
  its own account: one for BoilerIO (the controller and Danfoss bridge share a
  configuration file, so they share an account), one per sensor publisher, and
  one for anything else, such as Home Assistant.
- **Topics.** The topic names are set in the configuration file (section 7).
  With the defaults:

| Topic | Published by | Read by | Content |
| --- | --- | --- | --- |
| `heating/zone/demand` | Controller | Danfoss bridge | On/off requests, e.g. `{"thermostat": "0xbab1", "command": "O"}` |
| `heating/zone/info/<thermostat>` | Danfoss bridge | Nothing in BoilerIO; useful for monitoring | RF traffic seen or sent, e.g. `heating/zone/info/0xBAB1` with `{"thermostat": "0xBAB1", "direction": "ISSUE", "cmd": "ON"}`. The ID is in the firmware's uppercase hex. |
| Each sensor's topic, e.g. `emon_sensors/emonth1` | Sensor publisher | Controller | Readings (section 5) |

### Example: Mosquitto with BoilerIO

The broker's configuration goes in `/etc/boilerio`, alongside BoilerIO's
own configuration (section 7). Create the directory, then create each file
below with `sudoedit`, for example `sudoedit /etc/boilerio/mosquitto.conf`:

```bash
sudo install -d -m 0755 /etc/boilerio
```

`/etc/boilerio/mosquitto.conf`:

```text
persistence true
persistence_location /mosquitto/data/
log_dest stdout
per_listener_settings true

listener 1883
allow_anonymous false
password_file /mosquitto/config/passwd
acl_file /mosquitto/config/acl

# Health-check listener, reachable only inside the container.
listener 1884 127.0.0.1
allow_anonymous true
```

`/etc/boilerio/mosquitto.acl`:

```text
user boilerio
topic readwrite heating/#
topic read emon_sensors/#

user emonhub
topic write emon_sensors/#
```

Create the password file with `mosquitto_passwd`, which prompts for each
password. It isn't in the `mosquitto-clients` package, so run it from the
broker's image:

```bash
docker run --rm -it -v /etc/boilerio:/w -w /w eclipse-mosquitto:2.0.22 mosquitto_passwd -c mosquitto.passwd boilerio
docker run --rm -it -v /etc/boilerio:/w -w /w eclipse-mosquitto:2.0.22 mosquitto_passwd mosquitto.passwd emonhub
```

(It is also in the Debian `mosquitto` package, but that package starts its own
broker on port 1883, which stops the container's broker from starting. If you
install it, run `sudo systemctl disable --now mosquitto`.)

The container creates the file owned by root. Mosquitto runs as UID 1883 in
its container, so make both files readable by it and nobody else:

```bash
sudo chown 1883:1883 /etc/boilerio/mosquitto.passwd /etc/boilerio/mosquitto.acl
sudo chmod 0640 /etc/boilerio/mosquitto.passwd /etc/boilerio/mosquitto.acl
```

To run Mosquitto and BoilerIO in one Compose project, write your own
`compose.yaml` that defines the broker and reuses the BoilerIO services from
[`examples/compose.yaml`](../examples/compose.yaml) with `extends`:

```yaml
services:
  mosquitto:
    image: eclipse-mosquitto:2.0.22
    restart: unless-stopped
    ports: ["1883:1883"]
    volumes:
      - /etc/boilerio/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro
      - /etc/boilerio/mosquitto.passwd:/mosquitto/config/passwd:ro
      - /etc/boilerio/mosquitto.acl:/mosquitto/config/acl:ro
      - mosquitto-data:/mosquitto/data
    healthcheck:
      test: [CMD, mosquitto_sub, -h, "127.0.0.1", -p, "1884", -t, "$$SYS/broker/uptime", -C, "1", -W, "15"]
      interval: 30s
      timeout: 20s
      start_period: 20s

  controller:
    extends: {file: boilerio.compose.yaml, service: controller}
    depends_on: {mosquitto: {condition: service_healthy}}

  danfoss-bridge:
    extends: {file: boilerio.compose.yaml, service: danfoss-bridge}
    depends_on: {mosquitto: {condition: service_healthy}}

volumes:
  mosquitto-data:
```

Save this as `/opt/boilerio/compose.yaml`:

```bash
sudo install -d -m 0755 /opt/boilerio
sudoedit /opt/boilerio/compose.yaml
```

It extends BoilerIO's services from `boilerio.compose.yaml`, the example file
in this repository (which you could also use on its own with an existing
broker). Download it now, with the `.env` file it reads; you'll fill in `.env`
in section 8:

```bash
cd /opt/boilerio
sudo curl -fsSL -o boilerio.compose.yaml https://raw.githubusercontent.com/adpeace/boilerio/master/examples/compose.yaml
sudo curl -fsSL -o .env https://raw.githubusercontent.com/adpeace/boilerio/master/examples/compose.env.example
```

Then start just the broker, so you can check sensor readings in section 5, and
check that it becomes `healthy`:

```bash
docker compose up -d mosquitto
docker compose ps
```

Run the `docker compose` commands in this guide from `/opt/boilerio`. Based on
the setup above, BoilerIO's configuration file uses `host = mosquitto`
(section 7). Docker keeps the broker's persistent data in the `mosquitto-data`
volume, under `/var/lib/docker/volumes`.

To change users or the ACL later, edit the files with `sudo` (the `docker run`
commands above still work for adding users), then restart the broker by running
`docker compose restart mosquitto` in `/opt/boilerio`.

## 5. Sensors

The controller reads each zone's temperature from an MQTT topic. Each message
must be a JSON object containing:

| Field | Required | Meaning |
| --- | --- | --- |
| `temperature` | Yes | Degrees Celsius |
| `humidity` | Yes | Relative humidity, % |
| `battery` | No | Total battery voltage, in volts. At 2.0 V or below, the backend reports the battery as low. |

Values can be numbers or numeric strings. Other fields are ignored. For
example:

```json
{"temperature": 19.4, "humidity": 48.0, "battery": 2.9}
```

Messages without a temperature value are ignored.

### emonTH

emonTH sensors send their readings by radio to an RFM69 receiver, such as an
emonPi, emonBase or RFM2Pi board. There, emonhub decodes them and publishes
them to MQTT.

Upstream emonhub publishes each reading on its own topic (for example
`emon/emonth1/temperature`), which BoilerIO can't use. The tested setup uses
the [adpeace/emonhub](https://github.com/adpeace/emonhub) fork (`emon-pi`
branch), which adds a JSON format that publishes all of a node's readings in
one message. Enable it in the MQTT interfacer section of `emonhub.conf`:

```ini
[[MQTT]]
    Type = EmonHubMqttInterfacer
    [[[init_settings]]]
        mqtt_host = <broker>
        mqtt_port = 1883
        mqtt_user = emonhub
        mqtt_passwd = REPLACE_ME
    [[[runtimesettings]]]
        pubchannels = ToRFM12,
        subchannels = ToEmonCMS,
        json_format_enable = 1
        json_format_topic = emon_sensors/
```

Each node is then published to `emon_sensors/<nodename>`, using the
`nodename` from the node's section under `[nodes]`. The emonTH's default
field names are already the ones BoilerIO expects:

```ini
[[19]]
   nodename = emonth1
   [[[rx]]]
      names = temperature, external temperature, humidity, battery
      datacode = h
      scales = 0.1,0.1,0.1,0.1
      units = C,C,%,V
```

<!-- TODO: switch to upstream emonhub (2.1.7+), which has an equivalent
     built-in option: node_JSON_enable = 1, node_JSON_basetopic = emon_sensors/.
     It publishes numeric values (not strings) plus "time" instead of
     "timestamp_utc"; BoilerIO accepts either. Upstream's emonTH templates use
     nodename emonTH_N and the same field names. Untested here. -->

This is for the stock emonTH V2 firmware, which sends temperature in tenths of
a degree.

#### Optional: higher-precision temperature firmware

The emonTH V2's SI7021 sensor measures temperature to a hundredth of a degree,
but the stock firmware rounds it to tenths before sending. Finer readings let
the controller's PID control respond to directional changes sooner. The
`precision` branch of
[adpeace/emonth2](https://github.com/adpeace/emonth2/tree/precision) sends the
full resolution for internal temperature only.

To use it:

1. Build and upload the firmware from the `firmware` directory of the
   `precision` branch with [PlatformIO](https://platformio.org/), using a USB
   to serial (FTDI) programmer, as for the stock emonTH firmware:

   ```bash
   git clone --branch precision https://github.com/adpeace/emonth2.git
   cd emonth2/firmware
   pio run --target upload
   ```

2. Change the temperature scale for that node in `emonhub.conf` from `0.1` to
   `0.01`, and restart emonhub:

   ```ini
   [[19]]
      nodename = emonth1
      [[[rx]]]
         names = temperature, external temperature, humidity, battery
         datacode = h
         scales = 0.01,0.1,0.1,0.1
         units = C,C,%,V
   ```

> [!IMPORTANT]
> The scale in `emonhub.conf` must match the firmware on each sensor. If they
> don't match, temperatures are reported ten times too high or too low (for
> example 187.3 or 1.87 instead of 18.73), and BoilerIO will control your
> heating to the wrong value. Check the readings (below) after changing either.

<!-- TODO: this firmware is based on 2018 upstream and is 50 commits behind;
     rebase onto current upstream (now firmware/emonth2.ino) and check the
     PlatformIO configuration still builds. -->


### Other sensors

Any sensor works if something publishes messages in the format above. If yours
already publishes to MQTT in a different format, write a small bridge that
subscribes to its topic, converts each message, and republishes it to a topic
of your own.

### Check readings are arriving

The checks in this guide use the Mosquitto command-line clients. Install them
on the Pi (or wherever you run the checks):

```bash
sudo apt install mosquitto-clients
```

Before going further, check each sensor's readings reach the broker:

```bash
mosquitto_sub -h <broker> -u boilerio -P <password> -v -t 'emon_sensors/#'
```

For `<broker>`, use `localhost` if you run this on the Pi with section 4's
broker, or the broker's hostname or IP address from another machine. (The
name `mosquitto` only works from inside the Compose project's containers.)
Use the `boilerio` account: with the ACL above, `emonhub` can only write, so
subscribing as it succeeds but shows nothing.

You should see a message from each sensor within its reporting interval
(about a minute for an emonTH):

```text
emon_sensors/emonth1 {"temperature": "19.42", "humidity": "48.0", "battery": "2.9", "rssi": "-44", ...}
```

Note each sensor's topic: you will register it with the backend in section 6.

## 6. Backend

<!-- TODO: replace with a container-based setup once the backend has an
     image (see backend-dockerization-plan.md). -->

The backend is a Flask application backed by PostgreSQL. It can run on the
same Pi or on a separate machine. These steps are for Debian
or Raspberry Pi OS.

**Database.** Install PostgreSQL, create the `scheduler` role and the `boilerio`
database, then load the schema from [`scheduler.sql`](../scheduler.sql) as the
`postgres` superuser (the schema's tables are owned by `postgres` and granted
to `scheduler`, so the role must exist first):

```bash
sudo apt install postgresql
sudo -u postgres psql -c "CREATE ROLE scheduler LOGIN PASSWORD 'REPLACE_ME'"
sudo -u postgres createdb -O scheduler boilerio
curl -fsSL -o scheduler.sql https://raw.githubusercontent.com/adpeace/boilerio/master/scheduler.sql
sudo -u postgres psql -d boilerio < scheduler.sql
```

**Service user.** To run with least-privilege, the backend should use its own
`boilerio` system user:

```bash
sudo adduser --system --group --home /home/boilerio boilerio
```

**Install.** Install the backend, with the `web` extra, into a virtual
environment owned by that user. Create it with the system's `python3`:
uWSGI's Python plugin (below) runs that Python, so the environment must match
it. If a system upgrade moves to a new Python version, recreate the
environment. Install the same version as the controller image you're using
(see the [release notes](https://github.com/adpeace/boilerio/releases)):

```bash
sudo apt install python3-venv
sudo -u boilerio python3 -m venv /home/boilerio/venv
sudo -u boilerio /home/boilerio/venv/bin/pip install 'boilerio[web]==0.5.0'
```

**Settings.** Copy [`example-settings.cfg`](../example-settings.cfg) to
`settings.cfg` and fill in the database details (`DB_HOST = 'localhost'`,
`DB_NAME = 'boilerio'`, `DB_USER = 'scheduler'` and its password), a random
`SECRET_KEY` (this is used to sign session cookies: it's important for
security and should be a long, random string), your `GOOGLE_CLIENT_ID` (see below) and
your `HEATING_TIMEZONE`. Install it readable only by root and the `boilerio`
group:

```bash
sudo install -d -m 0755 /etc/boilerio
sudo install -o root -g boilerio -m 0640 settings.cfg /etc/boilerio/settings.cfg
```

**Google sign-in.** Create an OAuth client ID for the web UI's origin on the
Google developer site.

**Try it.** Flask's development server is enough to check the settings
(it listens on port 5000):

```bash
sudo -u boilerio env BOILERIO_SETTINGS=/etc/boilerio/settings.cfg \
  /home/boilerio/venv/bin/flask --app boilerio.backend.wsgi run --host 0.0.0.0
```

**Run it with uWSGI.** For real use, run the backend under
[uWSGI](https://uwsgi-docs.readthedocs.io/) behind a web server that
provides HTTPS, such as nginx. Install uWSGI and create the directory for
its socket, which the web server (group `www-data`) connects to:

```bash
sudo apt install uwsgi uwsgi-plugin-python3
sudo install -d -o boilerio -g www-data -m 0750 /var/www/boilerio
```

Save this as `/etc/uwsgi/apps-available/boilerio.ini`. The backend runs as
`boilerio:boilerio`, so it can read its settings, and the socket is handed to
the web server's group:

```ini
[uwsgi]
plugin = python3
env = BOILERIO_SETTINGS=/etc/boilerio/settings.cfg
venv = /home/boilerio/venv
module = boilerio.backend.wsgi:app
socket = /var/www/boilerio/boilerio.sock
uid = boilerio
gid = boilerio
chown-socket = boilerio:www-data
chmod-socket = 660
```

If uWSGI's log (`/var/log/uwsgi/app/boilerio.log`) says `unable to load app`,
look above that line for the reason, such as the settings file not being
readable.

Then enable it and restart uWSGI:

```bash
sudo ln -s /etc/uwsgi/apps-available/boilerio.ini /etc/uwsgi/apps-enabled/
sudo systemctl restart uwsgi
```

**Web server.** Point your HTTPS web server at the socket. A typical setup
serves the [web UI](https://github.com/adpeace/boilerio-ui) under a path such
as `/heating` and the API under `/heating/api`. With nginx, inside your HTTPS
`server` block:

```nginx
location /heating {
    # The web UI's files are served from your document root's heating/ directory.
    location /heating/api {
        try_files $uri @boilerio;
    }
}

location @boilerio {
    include uwsgi_params;
    uwsgi_pass unix:/var/www/boilerio/boilerio.sock;
}
```

nginx passes the full path to the backend, so tell the backend where its API
lives by adding this to `/etc/boilerio/settings.cfg`, then restart uWSGI:

```python
BASE_URL = '/heating/api'
```

The backend's URL for the controller and Home Assistant is then
`https://<your host>/heating/api`.

### Initial data

The UI can't create users, API keys, sensors or zones yet, so set them up
from the command line, as the `boilerio` user. To keep the commands short,
define this shell function first:

```bash
admin() {
  sudo -u boilerio env BOILERIO_SETTINGS=/etc/boilerio/settings.cfg \
    /home/boilerio/venv/bin/python -m boilerio.backend.admin "$@"
}
```

**Users.** Only accounts listed in the database can sign in. To find your
Google subscriber ID, set up the [web UI](https://github.com/adpeace/boilerio-ui)
now and sign in once: the login is rejected and the backend logs
`Reject login request for Google subscriber ID <id>`. Then add yourself:

```bash
admin add-user <id> --name "Your Name" --email you@example.com
```

The name and email are refreshed from your Google profile each time you sign
in, so they can be left out.

**API keys.** The controller logs in to the API with an API key: an ID and
a secret. Other clients, such as Home Assistant, use API keys too; create a
separate key for each. Create one for the controller:

```bash
admin add-api-key
```

This prints the key's ID and secret, and the `api_key_id` and
`api_key_secret` lines to put in the controller's configuration file
(section 7). The secret is stored only as a hash, so copy it now; if you lose
it, create another API key.

**Zones and sensors.** Each zone has a name, the thermostat ID BoilerIO
uses for it (`boiler_relay`), and the sensor that measures its temperature.
Each sensor's `locator` is its MQTT topic from section 5. Pick a thermostat
ID that differs from your existing thermostat's, e.g. `0xbab1`, and quote it
as a string. You will pair the receiver with it in section 9.

Zones and sensors refer to each other, so create each pair in one
transaction with `psql -h localhost -U scheduler boilerio`:

```sql
BEGIN;
INSERT INTO zones (name, boiler_relay) VALUES ('Downstairs', '0xbab1');
INSERT INTO sensor (name, locator, zone)
    VALUES ('Living room', 'emon_sensors/emonth1', currval('zones_zone_id_seq'));
UPDATE zones SET sensor_id = currval('sensor_sensor_id_seq')
    WHERE zone_id = currval('zones_zone_id_seq');
COMMIT;
```

Repeat for each zone. Check the result with:

```sql
SELECT z.zone_id, z.name, z.boiler_relay, s.sensor_id, s.name, s.locator
FROM zones z JOIN sensor s ON s.sensor_id = z.sensor_id;
```

The controller loads zones and sensors when it starts, so restart it after
changing them.

## 7. Configuration file (back on the Pi)

The controller and Danfoss bridge read one INI file,
`/etc/boilerio/config.ini`, which is mounted into their containers. The
containers run as UID/GID 10001, so create the file readable by that group
and nobody else, then edit it:

```bash
sudo install -d -m 0755 /etc/boilerio
sudo install -o root -g 10001 -m 0640 /dev/null /etc/boilerio/config.ini
sudoedit /etc/boilerio/config.ini
```

Use this as a starting point, with your values:

```ini
[mqtt]
# The broker's address as seen from inside the container. If the broker is in
# the same Compose project, use its service name (e.g. mosquitto), not
# localhost: inside a container, localhost is the container itself.
host = mosquitto
user = boilerio
password = REPLACE_ME

[heating]
# Topic names. Any names work, as long as every component uses the same ones.
info_basetopic = heating/zone/info
demand_request_topic = heating/zone/demand

# Backend API base URL, without a trailing slash (e.g.
# https://heating.example.com/api), and the API key ID and secret from
# section 6. If the backend runs on the same Pi, use the Pi's LAN address or
# hostname here, not localhost (localhost is the container itself), and make
# sure the backend listens on that address.
backend_url = https://REPLACE_ME
api_key_id = REPLACE_ME
api_key_secret = REPLACE_ME

[weather]
# Required. OpenWeatherMap API key and location, used to estimate how long
# heating will take. A free key from https://openweathermap.org/api is enough.
# With an invalid key the controller logs errors but still controls heating.
apikey = REPLACE_ME
location = London,UK
```

Keep explanations on their own `#` lines: a comment at the end of a value line
becomes part of the value.

## 8. Running with Docker Compose

We're putting the deployment in `/opt/boilerio` in this guide. If you're running
Mosquitto as in section 4, you've already downloaded the necessary files there.
If you use an existing broker instead, download
[`examples/compose.yaml`](../examples/compose.yaml) as the deployment's
`compose.yaml`, with
[`examples/compose.env.example`](../examples/compose.env.example) as `.env`:

```bash
sudo install -d -m 0755 /opt/boilerio
cd /opt/boilerio
sudo curl -fsSL -o compose.yaml https://raw.githubusercontent.com/adpeace/boilerio/master/examples/compose.yaml
sudo curl -fsSL -o .env https://raw.githubusercontent.com/adpeace/boilerio/master/examples/compose.env.example
```

Run the `docker compose` commands in this guide from `/opt/boilerio`.

Edit `.env` with `sudoedit /opt/boilerio/.env`:

- **`BOILERIO_IMAGE`**: the image reference from the
  [release notes](https://github.com/adpeace/boilerio/releases). It is pinned
  by digest, so it never changes under you. To run unreleased code instead,
  build the image on the Pi with
  `docker build -t boilerio:local https://github.com/adpeace/boilerio.git`
  and set `BOILERIO_IMAGE=boilerio:local`.
- **`BOILER_DEVICE`**: the JeeLink's stable device path. Use the path under
  `/dev/serial/by-id/` rather than `/dev/ttyUSB0`, which can change between
  boots. To find it:

  ```bash
  ls -l /dev/serial/by-id/
  ```

- **`SERIAL_GID`**: the numeric group that owns the device, which lets the
  container use it:

  ```bash
  stat -Lc %g /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_XXXXXXXX-if00-port0
  ```

- **`TZ`**: your local timezone, for the containers' log timestamps. The
  heating schedule's timezone comes from the backend (`HEATING_TIMEZONE`).
- **`BOILERIO_CONFIG`** and **`BOILERIO_STATE_DIR`**, if you are not using the
  defaults.

A filled-in `.env` looks like this; you can paste it in and change the values:

```ini
BOILERIO_IMAGE=ghcr.io/adpeace/boilerio-controller@sha256:<digest from the release notes>
TZ=Europe/London
BOILERIO_CONFIG=/etc/boilerio/config.ini
BOILERIO_STATE_DIR=/var/lib/boilerio
BOILER_DEVICE=/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_XXXXXXXX-if00-port0
SERIAL_GID=20
```

Create the state directory, where the controller caches its configuration and
schedule:

```bash
sudo install -d -m 0750 -o 10001 -g 10001 /var/lib/boilerio
```

Check the configuration, then start the Danfoss bridge on its own.
`docker compose config` only checks that the files are valid, so first make
sure no placeholders are left (`grep -E 'REPLACE_ME|XXXXXXXX|<' .env` should
print nothing):

```bash
docker compose config --quiet
docker compose up -d danfoss-bridge
docker compose logs danfoss-bridge
```

Look for:

```text
Device welcome banner received: Operating normally
```

Then start everything:

```bash
docker compose up -d
docker compose ps
docker compose logs -f controller
```

The receiver isn't paired yet, so the controller's commands have no effect
until section 9.

The controller only heats a zone once it has a schedule. If you haven't
already, sign in to the web UI and add at least one schedule entry for each
zone. Until a zone has a target temperature, its heating stays off.

### Troubleshooting

- **`Permission denied` opening the serial device.** `SERIAL_GID` doesn't
  match the device's group. Check it with `stat` as above, fix `.env`, and
  run `docker compose up -d danfoss-bridge`, which recreates the container.
- **`error gathering device information` when starting `danfoss-bridge`.** The
  JeeLink isn't plugged in, or `BOILER_DEVICE` is wrong. The container stays
  in `Created` and doesn't retry, so after reconnecting the JeeLink, run
  `docker compose up -d danfoss-bridge`. This can also happen after a reboot if
  the JeeLink is detected after Docker starts.
- **No welcome banner.** Check you are using the right by-id path. The banner
  appears only when the JeeLink resets; unplugging it and plugging it back in
  forces one.
- **MQTT connection refused or not authorised.** Check the `[mqtt]` section
  and the broker's ACL. `host = localhost` won't work from inside a container.
- **`No such file or directory` for the config file or state directory, or
  `bind source path does not exist`.** Compose doesn't create these for you:
  create them as shown above, at the paths in `.env`.
- **The controller exits at startup** with `No valid startup configuration
  available from server or cache`. On its first start it must reach the
  backend to download its configuration. Check `backend_url` and the API key
  credentials (wrong credentials show `(status 401)` in the lines before).
  After one successful start, it can start from its cache.

## 9. Pair the Danfoss bridge with the receiver

This is the step that hands control of your boiler to BoilerIO.

Danfoss receivers learn a transmitter's ID while it is sending learn signals.
Normally the thermostat does this for a few minutes after you put it into
learn mode; here, the Danfoss bridge sends them instead, using the zone's thermostat
ID (its `boiler_relay` from section 6).

1. Stop the controller so it doesn't send commands during pairing:
   `docker compose stop controller`.
2. Start sending learn signals, and leave this running:

   ```bash
   while true; do
     mosquitto_pub -h <broker> -u boilerio -P <password> -t heating/zone/demand \
       -m '{"command": "L", "thermostat": "0xbab1"}'
     sleep 1
   done
   ```

   The ID must be a quoted string; otherwise the bridge logs
   `Error parsing request` and sends nothing. `docker compose logs -f danfoss-bridge`
   in another terminal should show a `Publishing update` line with
   `"direction": "ISSUE", "cmd": "LEARN"` each second.
3. On the receiver, press and hold **PROG** (the left-hand button) together
   with the channel button for this zone (**CH1**, or **CH2**/**CH3** for a
   second or third zone on an RX2 or RX3) for about 3 seconds, until the green
   light flashes.
4. Stop the loop with Ctrl-C, then start the controller again:
   `docker compose up -d controller`.

For more than one zone, pair one channel at a time, with only that zone's ID
being sent.

These are the steps in Danfoss's RX1/RX2/RX3 commissioning instructions. On
the newer **RX1-S V2**, press PROG and CH together until the button lights
flash; see its
[installation guide](https://assets.danfoss.com/documents/260400/AN30483496955101-000102.pdf).

To go back to your old thermostat, put it into learn mode (see its manual; on
many models, hold its two buttons for 3 seconds) and repeat step 3 for the same
channel, then check that adjusting the thermostat controls the boiler as
epxected.

## 10. Verifying

- **Heating turns on and off.** Set a target above and then below the room
  temperature, using an override from the UI or the schedule. Within a minute,
  watch the demand and info topics:

  ```bash
  mosquitto_sub -h <broker> -u boilerio -P <password> -v -t 'heating/#'
  ```

  You should see `"command": "O"` (on) or `"command": "X"` (off) on
  `heating/zone/demand`, then `ISSUE ... ON` or `OFF` from the bridge, and the
  receiver should respond.
- **Sensor readings reach the backend.** The UI shows current temperatures,
  or call `GET /sensor/summary` on the API.
- **Heating continues while the backend is offline.** Make the backend
  unreachable from the Pi and restart the controller. Its log should show
  `Using backup /var/lib/boilerio/configuration (... seconds old)` along with
  errors reaching the backend, and heating should continue on the cached
  schedule.
- **Everything comes back after a reboot.** Reboot the Pi and check
  `docker compose ps`. The services use `restart: unless-stopped`, so they
  return unless you stopped them by hand. If `danfoss-bridge` is stuck in
  `Created`, see the `error gathering device information` troubleshooting
  entry in section 8.
