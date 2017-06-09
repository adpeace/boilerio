--
-- PostgreSQL database dump
--

SET statement_timeout = 0;
SET lock_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET client_min_messages = warning;

--
-- Name: plpgsql; Type: EXTENSION; Schema: -; Owner: 
--

CREATE EXTENSION IF NOT EXISTS plpgsql WITH SCHEMA pg_catalog;


--
-- Name: EXTENSION plpgsql; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION plpgsql IS 'PL/pgSQL procedural language';


SET search_path = public, pg_catalog;

SET default_tablespace = '';

SET default_with_oids = false;

--
-- Name: override; Type: TABLE; Schema: public; Owner: postgres; Tablespace: 
--

CREATE TABLE override (
    until timestamp without time zone,
    temp double precision
);


ALTER TABLE override OWNER TO postgres;

--
-- Name: schedule; Type: TABLE; Schema: public; Owner: postgres; Tablespace: 
--

CREATE TABLE schedule (
    day smallint NOT NULL,
    starttime time without time zone NOT NULL,
    temp double precision,
    CONSTRAINT schedule_day_check CHECK (((day >= 0) AND (day < 7)))
);


ALTER TABLE schedule OWNER TO postgres;

--
-- Name: temperature_cache; Type: TABLE; Schema: public; Owner: postgres; Tablespace: 
--

CREATE TABLE temperature_cache (
    temperature double precision,
    updated timestamp without time zone
);


ALTER TABLE temperature_cache OWNER TO postgres;

--
-- Name: schedule_pkey1; Type: CONSTRAINT; Schema: public; Owner: postgres; Tablespace: 
--

ALTER TABLE ONLY schedule
    ADD CONSTRAINT schedule_pkey1 PRIMARY KEY (day, starttime);


--
-- Name: public; Type: ACL; Schema: -; Owner: postgres
--

REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM postgres;
GRANT ALL ON SCHEMA public TO postgres;
GRANT ALL ON SCHEMA public TO PUBLIC;


--
-- Name: override; Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON TABLE override FROM PUBLIC;
REVOKE ALL ON TABLE override FROM postgres;
GRANT ALL ON TABLE override TO postgres;
GRANT ALL ON TABLE override TO scheduler;


--
-- Name: schedule; Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON TABLE schedule FROM PUBLIC;
REVOKE ALL ON TABLE schedule FROM postgres;
GRANT ALL ON TABLE schedule TO postgres;
GRANT ALL ON TABLE schedule TO scheduler;


--
-- Name: temperature_cache; Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON TABLE temperature_cache FROM PUBLIC;
REVOKE ALL ON TABLE temperature_cache FROM postgres;
GRANT ALL ON TABLE temperature_cache TO postgres;
GRANT ALL ON TABLE temperature_cache TO scheduler;


--
-- PostgreSQL database dump complete
--

