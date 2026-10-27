-- Esquema PostgreSQL + PostGIS del sistema de riesgo de incendios (Región de Valparaíso)
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE comunas (
    id         SERIAL PRIMARY KEY,
    nombre     TEXT UNIQUE NOT NULL,
    lat        DOUBLE PRECISION NOT NULL,
    lon        DOUBLE PRECISION NOT NULL,
    ndvi       REAL NOT NULL,          -- índice de vegetación (valor ESTIMADO de referencia)
    pendiente  REAL NOT NULL,          -- pendiente media en grados (valor ESTIMADO)
    geom       geometry(Point, 4326)
);

INSERT INTO comunas (nombre, lat, lon, ndvi, pendiente) VALUES
    ('Valparaíso',    -33.0472, -71.6127, 0.42, 22),
    ('Viña del Mar',  -33.0245, -71.5518, 0.45, 18),
    ('Quilpué',       -33.0480, -71.4420, 0.50, 15),
    ('Villa Alemana', -33.0422, -71.3733, 0.52, 12),
    ('Concón',        -32.9300, -71.5180, 0.40, 10),
    ('Quillota',      -32.8800, -71.2490, 0.58,  8),
    ('Limache',       -33.0170, -71.2650, 0.60, 14),
    ('Casablanca',    -33.3190, -71.4080, 0.55,  9),
    ('San Antonio',   -33.5933, -71.6217, 0.38, 11),
    ('Los Andes',     -32.8337, -70.5983, 0.35, 20);

UPDATE comunas SET geom = ST_SetSRID(ST_MakePoint(lon, lat), 4326);
CREATE INDEX idx_comunas_geom ON comunas USING GIST (geom);

CREATE TABLE usuarios (
    usuario    TEXT PRIMARY KEY,
    hash       TEXT NOT NULL,                       -- bcrypt, nunca texto plano
    rol        TEXT NOT NULL CHECK (rol IN ('admin', 'analista')),
    creado_en  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE consultas (
    id              BIGSERIAL PRIMARY KEY,
    comuna_id       INT NOT NULL REFERENCES comunas(id),
    usuario         TEXT NOT NULL,
    variables       JSONB NOT NULL,
    nivel           TEXT NOT NULL,
    probabilidades  JSONB NOT NULL,
    modelo_version  TEXT NOT NULL,
    geom            geometry(Point, 4326),
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_consultas_fecha ON consultas (creado_en DESC);
CREATE INDEX idx_consultas_geom  ON consultas USING GIST (geom);

CREATE TABLE alertas (
    id           BIGSERIAL PRIMARY KEY,
    consulta_id  BIGINT REFERENCES consultas(id),
    comuna       TEXT NOT NULL,
    nivel        TEXT NOT NULL,
    mensaje      TEXT NOT NULL,
    creado_en    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_alertas_fecha ON alertas (creado_en DESC);
