-- Table for detected anomalies
CREATE TABLE IF NOT EXISTS OBD2Anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    variable TEXT,
    value REAL,
    description TEXT
);
