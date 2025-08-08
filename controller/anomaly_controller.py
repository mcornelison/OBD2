import sqlite3
import json
from datetime import datetime
from model.anomaly_model import AnomalyModel

class AnomalyController:
    def __init__(self, anomaly_model):
        self.model = anomaly_model
        with open("config.json", "r") as f:
            config = json.load(f)
        db_path = config.get("database", {}).get("path", "./sql/obd2_data.db")
        self.conn = sqlite3.connect(db_path)
        # Load anomaly thresholds once
        with open("anomaly_thresholds.json", "r") as f:
            self.thresholds = json.load(f)

    def detect_and_store(self, streaming_data, thresholds=None):
        # Use provided thresholds or default to self.thresholds
        if thresholds is None:
            thresholds = self.thresholds
        anomalies = []
        now = datetime.now().isoformat()
        for field, limits in thresholds.items():
            value = getattr(streaming_data, field, None)
            if value is not None:
                min_val = limits.get("min")
                max_val = limits.get("max")
                if (min_val is not None and value < min_val) or (max_val is not None and value > max_val):
                    description = f"{field} out of range: {value} (expected {min_val}-{max_val})"
                    anomalies.append({
                        'timestamp': now,
                        'variable': field,
                        'value': value,
                        'description': description
                    })
        for anomaly in anomalies:
            self.model.add_anomaly(anomaly)
            self.conn.execute('''INSERT INTO OBD2Anomalies (timestamp, variable, value, description) VALUES (?, ?, ?, ?)''',
                              (anomaly['timestamp'], anomaly['variable'], anomaly['value'], anomaly['description']))
        self.conn.commit()

    def close(self):
        self.conn.close()
