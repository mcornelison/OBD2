from model.obd2_connection import OBD2Connection

import json
import time
from datetime import datetime

from controller.anomaly_controller import AnomalyController
from model.anomaly_model import AnomalyModel

import sqlite3

class OBD2Controller:
    def __init__(self, bt_address, model, view):
        self.connection = OBD2Connection(bt_address)
        self.model = model
        self.view = view
        with open("config.json", "r") as f:
            config = json.load(f)
        streaming_cfg = config.get("streaming", {})
        self.interval = 1.0 / streaming_cfg.get("interval_hz", 1)
        self.end_time = streaming_cfg.get("end_time")
        # Initialize anomaly detection
        self.anomaly_model = AnomalyModel()
        self.anomaly_controller = AnomalyController(self.anomaly_model)
        # Database connection for streaming data
        db_path = config.get("database", {}).get("path", "./sql/obd2_data.db")
        self.db_conn = sqlite3.connect(db_path)

    def run(self):
        self.connection.connect()
        static_data = self.connection.read_static_data()
        self.model.set_data({
            'static': static_data,
            'streaming': None
        })
        self.view.display(self.model.get_data())

        # Streaming loop
        start_time = time.time()
        if self.end_time:
            try:
                end_timestamp = datetime.fromisoformat(self.end_time).timestamp()
            except Exception:
                end_timestamp = None
        else:
            end_timestamp = None

        try:
            while True:
                now = datetime.now()
                if end_timestamp and now.timestamp() >= end_timestamp:
                    break
                streaming_data = self.connection.read_streaming_data()
                self.model.set_data({
                    'static': static_data,
                    'streaming': streaming_data,
                    'datetime': now.isoformat()
                })
                self.view.display(self.model.get_data())
                # Run anomaly detection after reading streaming data
                self.anomaly_controller.detect_and_store(streaming_data)
                # Save streaming data to DB
                self.save_streaming_data_to_db(streaming_data, now)
                time.sleep(self.interval)
        except KeyboardInterrupt:
            print("Streaming stopped by user.")
        finally:
            self.connection.disconnect()
            self.anomaly_controller.close()
            self.db_conn.close()

    def save_streaming_data_to_db(self, streaming_data, now):
        # Save all fields of streaming_data to the database
        fields = streaming_data.__dataclass_fields__.keys()
        values = [getattr(streaming_data, field) for field in fields]
        # Add timestamp
        fields = list(fields) + ["timestamp"]
        values = values + [now.isoformat()]
        placeholders = ','.join(['?'] * len(fields))
        sql = f"INSERT INTO OBD2StreamingData ({','.join(fields)}) VALUES ({placeholders})"
        try:
            self.db_conn.execute(sql, values)
            self.db_conn.commit()
        except Exception as e:
            print(f"Failed to save streaming data: {e}")
