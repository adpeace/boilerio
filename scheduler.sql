--
-- PostgreSQL database dump
--

-- Dumped from database version 9.5.14
-- Dumped by pg_dump version 9.5.14

SET statement_timeout = 0;
SET lock_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: plpgsql; Type: EXTENSION; Schema: -; Owner: 
--

CREATE EXTENSION IF NOT EXISTS plpgsql WITH SCHEMA pg_catalog;


--
-- Name: EXTENSION plpgsql; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION plpgsql IS 'PL/pgSQL procedural language';


--
-- Name: sensor_metric_type; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.sensor_metric_type AS ENUM (
    'temperature',
    'battery_voltage',
    'humidity'
);


ALTER TYPE public.sensor_metric_type OWNER TO postgres;

SET default_tablespace = '';

SET default_with_oids = false;

--
-- Name: device; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.device (
    device_id integer NOT NULL,
    device_secret_hashed character varying(256) NOT NULL,
    salt character varying(64) NOT NULL
);


ALTER TABLE public.device OWNER TO postgres;

--
-- Name: device_device_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.device ALTER COLUMN device_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.device_device_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: device_reported_state; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.device_reported_state (
    zone_id integer NOT NULL,
    received timestamp without time zone NOT NULL,
    state character varying(20),
    target double precision,
    current_temp double precision,
    time_to_target integer,
    current_outside_temp double precision,
    target_overridden boolean,
    dutycycle double precision
);


ALTER TABLE public.device_reported_state OWNER TO postgres;

--
-- Name: gradient_measurement; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.gradient_measurement (
    id integer NOT NULL,
    "when" timestamp without time zone,
    delta double precision,
    gradient double precision,
    zone integer NOT NULL
);


ALTER TABLE public.gradient_measurement OWNER TO postgres;

--
-- Name: gradient_measurement_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.gradient_measurement_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.gradient_measurement_id_seq OWNER TO postgres;

--
-- Name: gradient_measurement_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.gradient_measurement_id_seq OWNED BY public.gradient_measurement.id;


--
-- Name: override; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.override (
    until timestamp without time zone,
    temp double precision,
    zone integer NOT NULL
);


ALTER TABLE public.override OWNER TO postgres;

--
-- Name: schedule; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.schedule (
    day smallint NOT NULL,
    starttime time without time zone NOT NULL,
    temp double precision,
    zone integer NOT NULL,
    CONSTRAINT schedule_day_check CHECK (((day >= 0) AND (day < 7)))
);


ALTER TABLE public.schedule OWNER TO postgres;

--
-- Name: sensor; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.sensor (
    sensor_id integer NOT NULL,
    locator character varying(100),
    name character varying(100)
);


ALTER TABLE public.sensor OWNER TO postgres;

--
-- Name: sensor_reading; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.sensor_reading (
    sensor_id integer NOT NULL,
    metric_type public.sensor_metric_type NOT NULL,
    "time" timestamp without time zone NOT NULL,
    value double precision
);


ALTER TABLE public.sensor_reading OWNER TO postgres;

--
-- Name: sensor_sensor_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.sensor_sensor_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.sensor_sensor_id_seq OWNER TO postgres;

--
-- Name: sensor_sensor_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.sensor_sensor_id_seq OWNED BY public.sensor.sensor_id;


--
-- Name: zones; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.zones (
    zone_id integer NOT NULL,
    name character varying(30),
    boiler_relay character varying(50) NOT NULL,
    sensor_id integer
);


ALTER TABLE public.zones OWNER TO postgres;

--
-- Name: zones_zone_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.zones_zone_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.zones_zone_id_seq OWNER TO postgres;

--
-- Name: zones_zone_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.zones_zone_id_seq OWNED BY public.zones.zone_id;


--
-- Name: id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.gradient_measurement ALTER COLUMN id SET DEFAULT nextval('public.gradient_measurement_id_seq'::regclass);


--
-- Name: sensor_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sensor ALTER COLUMN sensor_id SET DEFAULT nextval('public.sensor_sensor_id_seq'::regclass);


--
-- Name: zone_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.zones ALTER COLUMN zone_id SET DEFAULT nextval('public.zones_zone_id_seq'::regclass);


--
-- Name: device_reported_state_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_reported_state
    ADD CONSTRAINT device_reported_state_pkey PRIMARY KEY (zone_id, received);


--
-- Name: gradient_measurement_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.gradient_measurement
    ADD CONSTRAINT gradient_measurement_pkey PRIMARY KEY (id);


--
-- Name: override_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.override
    ADD CONSTRAINT override_pkey PRIMARY KEY (zone);


--
-- Name: schedule_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.schedule
    ADD CONSTRAINT schedule_pkey PRIMARY KEY (day, starttime, zone);


--
-- Name: sensor_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sensor
    ADD CONSTRAINT sensor_pkey PRIMARY KEY (sensor_id);


--
-- Name: sensor_reading_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sensor_reading
    ADD CONSTRAINT sensor_reading_pkey PRIMARY KEY (sensor_id, metric_type, "time");


--
-- Name: zones_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.zones
    ADD CONSTRAINT zones_pkey PRIMARY KEY (zone_id);


--
-- Name: sensor_reading_sensor_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX sensor_reading_sensor_time ON public.sensor_reading USING btree (sensor_id, "time");


--
-- Name: fkey_zone; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.gradient_measurement
    ADD CONSTRAINT fkey_zone FOREIGN KEY (zone) REFERENCES public.zones(zone_id);


--
-- Name: fkey_zone_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_reported_state
    ADD CONSTRAINT fkey_zone_id FOREIGN KEY (zone_id) REFERENCES public.zones(zone_id);


--
-- Name: sensor_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.zones
    ADD CONSTRAINT sensor_fkey FOREIGN KEY (sensor_id) REFERENCES public.sensor(sensor_id);


--
-- Name: sensor_reading_sensor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sensor_reading
    ADD CONSTRAINT sensor_reading_sensor_id_fkey FOREIGN KEY (sensor_id) REFERENCES public.sensor(sensor_id);


--
-- Name: zone_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.schedule
    ADD CONSTRAINT zone_fkey FOREIGN KEY (zone) REFERENCES public.zones(zone_id);


--
-- Name: zone_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.override
    ADD CONSTRAINT zone_fkey FOREIGN KEY (zone) REFERENCES public.zones(zone_id);


--
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: postgres
--

REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM postgres;
GRANT ALL ON SCHEMA public TO postgres;
GRANT ALL ON SCHEMA public TO PUBLIC;


--
-- Name: TABLE device; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.device TO scheduler;


--
-- Name: TABLE device_reported_state; Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON TABLE public.device_reported_state FROM PUBLIC;
REVOKE ALL ON TABLE public.device_reported_state FROM postgres;
GRANT ALL ON TABLE public.device_reported_state TO postgres;
GRANT ALL ON TABLE public.device_reported_state TO scheduler;


--
-- Name: TABLE gradient_measurement; Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON TABLE public.gradient_measurement FROM PUBLIC;
REVOKE ALL ON TABLE public.gradient_measurement FROM postgres;
GRANT ALL ON TABLE public.gradient_measurement TO postgres;
GRANT ALL ON TABLE public.gradient_measurement TO scheduler;


--
-- Name: SEQUENCE gradient_measurement_id_seq; Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON SEQUENCE public.gradient_measurement_id_seq FROM PUBLIC;
REVOKE ALL ON SEQUENCE public.gradient_measurement_id_seq FROM postgres;
GRANT ALL ON SEQUENCE public.gradient_measurement_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.gradient_measurement_id_seq TO scheduler;


--
-- Name: TABLE override; Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON TABLE public.override FROM PUBLIC;
REVOKE ALL ON TABLE public.override FROM postgres;
GRANT ALL ON TABLE public.override TO postgres;
GRANT ALL ON TABLE public.override TO scheduler;


--
-- Name: TABLE schedule; Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON TABLE public.schedule FROM PUBLIC;
REVOKE ALL ON TABLE public.schedule FROM postgres;
GRANT ALL ON TABLE public.schedule TO postgres;
GRANT ALL ON TABLE public.schedule TO scheduler;


--
-- Name: TABLE sensor; Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON TABLE public.sensor FROM PUBLIC;
REVOKE ALL ON TABLE public.sensor FROM postgres;
GRANT ALL ON TABLE public.sensor TO postgres;
GRANT ALL ON TABLE public.sensor TO scheduler;


--
-- Name: TABLE sensor_reading; Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON TABLE public.sensor_reading FROM PUBLIC;
REVOKE ALL ON TABLE public.sensor_reading FROM postgres;
GRANT ALL ON TABLE public.sensor_reading TO postgres;
GRANT ALL ON TABLE public.sensor_reading TO scheduler;


--
-- Name: TABLE zones; Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON TABLE public.zones FROM PUBLIC;
REVOKE ALL ON TABLE public.zones FROM postgres;
GRANT ALL ON TABLE public.zones TO postgres;
GRANT ALL ON TABLE public.zones TO scheduler;


--
-- PostgreSQL database dump complete
--

