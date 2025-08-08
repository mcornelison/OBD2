CREATE TABLE OBD2Anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    static_data_id INTEGER,
    timestamp TEXT,
    variable TEXT,
    value REAL,
    description TEXT,
    FOREIGN KEY(static_data_id) REFERENCES OBD2StaticData(id)
);
