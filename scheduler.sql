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


SET default_tablespace = '';

SET default_with_oids = false;

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
-- Name: state_cache; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.state_cache (
    state character varying(10),
    updated timestamp without time zone
);


ALTER TABLE public.state_cache OWNER TO postgres;

--
-- Name: temperature_cache; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.temperature_cache (
    temperature double precision,
    updated timestamp without time zone,
    zone integer
);


ALTER TABLE public.temperature_cache OWNER TO postgres;

--
-- Name: zones; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.zones (
    zone_id integer NOT NULL,
    name character varying(30),
    boiler_relay character varying(50) NOT NULL,
    sensor character varying(50) NOT NULL
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
-- Name: zone_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.zones ALTER COLUMN zone_id SET DEFAULT nextval('public.zones_zone_id_seq'::regclass);


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
-- Name: zones_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.zones
    ADD CONSTRAINT zones_pkey PRIMARY KEY (zone_id);


--
-- Name: zone_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.temperature_cache
    ADD CONSTRAINT zone_fkey FOREIGN KEY (zone) REFERENCES public.zones(zone_id);


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
-- Name: TABLE state_cache; Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON TABLE public.state_cache FROM PUBLIC;
REVOKE ALL ON TABLE public.state_cache FROM postgres;
GRANT ALL ON TABLE public.state_cache TO postgres;
GRANT ALL ON TABLE public.state_cache TO scheduler;


--
-- Name: TABLE temperature_cache; Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON TABLE public.temperature_cache FROM PUBLIC;
REVOKE ALL ON TABLE public.temperature_cache FROM postgres;
GRANT ALL ON TABLE public.temperature_cache TO postgres;
GRANT ALL ON TABLE public.temperature_cache TO scheduler;


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

