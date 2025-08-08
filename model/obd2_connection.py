import obd
import requests
import json
from .obd2_schema import OBD2StaticData, OBD2StreamingData

# Centralized config loader
class Config:
    def __init__(self, path="config.json"):
        with open(path, "r") as f:
            self.data = json.load(f)
    def get(self, key, default=None):
        return self.data.get(key, default)
    def get_nested(self, *keys, default=None):
        d = self.data
        for k in keys:
            d = d.get(k, default)
            if d is default:
                break
        return d

class OBD2Connection:
    def __init__(self, bt_address, config=None):
        self.bt_address = bt_address
        self.connection = None
        self.config = config if config else Config()

    def connect(self):
        self.connection = obd.OBD(f"bluetooth://{self.bt_address}")

    def disconnect(self):
        if self.connection:
            self.connection.close()
            self.connection = None

    def read_static_data(self):
        vin = self.connection.query(obd.commands.VIN).value if self.connection.query(obd.commands.VIN).is_successful() else None
        calibration_id = self.connection.query(obd.commands.CALID).value if self.connection.query(obd.commands.CALID).is_successful() else None
        ecu_name = self.connection.query(obd.commands.ECU_NAME).value if self.connection.query(obd.commands.ECU_NAME).is_successful() else None
        fuel_type = self.connection.query(obd.commands.FUEL_TYPE).value if self.connection.query(obd.commands.FUEL_TYPE).is_successful() else None
        engine_displacement = self.connection.query(obd.commands.ENGINE_DISPLACEMENT).value if self.connection.query(obd.commands.ENGINE_DISPLACEMENT).is_successful() else None

        # Check if VIN is already in DB
        make = model = year = body_class = engine_cylinders = engine_hp = plant_country = None
        vin_str = str(vin) if vin else None
        vin_found = False
        try:
            db_path = self.config.get_nested("database", "path", default="./sql/obd2_data.db")
            import sqlite3
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT make, model, year, body_class, engine_cylinders, engine_hp, plant_country FROM OBD2StaticData WHERE vin=?", (vin_str,))
            row = cursor.fetchone()
            if row:
                make, model, year, body_class, engine_cylinders, engine_hp, plant_country = row
                vin_found = True
            conn.close()
        except Exception as e:
            print(f"VIN DB check failed: {e}")

        # VIN decoder API lookup only if not found in DB
        if not vin_found:
            try:
                api_url = self.config.get_nested("vin_decoder", "api_url", default="")
                if vin and api_url:
                    url = api_url.replace("{vin}", vin_str)
                    resp = requests.get(url)
                    if resp.status_code == 200:
                        data = resp.json()
                        results = data.get("Results", [{}])[0]
                        make = results.get("Make")
                        model = results.get("Model")
                        year = results.get("ModelYear")
                        body_class = results.get("BodyClass")
                        engine_cylinders = results.get("EngineCylinders")
                        engine_hp = results.get("EngineHP")
                        plant_country = results.get("PlantCountry")
            except Exception as e:
                print(f"VIN decode failed: {e}")

        static_data = OBD2StaticData(
            vin=vin_str,
            calibration_id=str(calibration_id) if calibration_id else None,
            ecu_name=str(ecu_name) if ecu_name else None,
            fuel_type=str(fuel_type) if fuel_type else None,
            engine_displacement=float(engine_displacement) if engine_displacement else None,
            make=make,
            model=model,
            year=year,
            body_class=body_class,
            engine_cylinders=engine_cylinders,
            engine_hp=engine_hp,
            plant_country=plant_country
        )

        # Save static data to DB if not already present
        if not vin_found:
            try:
                db_path = self.config.get_nested("database", "path", default="./sql/obd2_data.db")
                import sqlite3
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("INSERT INTO OBD2StaticData (vin, calibration_id, ecu_name, fuel_type, engine_displacement, make, model, year, body_class, engine_cylinders, engine_hp, plant_country) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (static_data.vin, static_data.calibration_id, static_data.ecu_name, static_data.fuel_type, static_data.engine_displacement, static_data.make, static_data.model, static_data.year, static_data.body_class, static_data.engine_cylinders, static_data.engine_hp, static_data.plant_country))
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"Failed to save static data: {e}")

        return static_data

    def read_streaming_data(self):
        rpm = self.connection.query(obd.commands.RPM).value if self.connection.query(obd.commands.RPM).is_successful() else None
        speed = self.connection.query(obd.commands.SPEED).value if self.connection.query(obd.commands.SPEED).is_successful() else None
        coolant_temp = self.connection.query(obd.commands.COOLANT_TEMP).value if self.connection.query(obd.commands.COOLANT_TEMP).is_successful() else None
        throttle_pos = self.connection.query(obd.commands.THROTTLE_POS).value if self.connection.query(obd.commands.THROTTLE_POS).is_successful() else None
        maf = self.connection.query(obd.commands.MAF).value if self.connection.query(obd.commands.MAF).is_successful() else None
        fuel_level = self.connection.query(obd.commands.FUEL_LEVEL).value if self.connection.query(obd.commands.FUEL_LEVEL).is_successful() else None
        intake_temp = self.connection.query(obd.commands.INTAKE_TEMP).value if self.connection.query(obd.commands.INTAKE_TEMP).is_successful() else None
        dtc_count = self.connection.query(obd.commands.DTC_NUMBER).value if self.connection.query(obd.commands.DTC_NUMBER).is_successful() else None
        return OBD2StreamingData(
            rpm=int(rpm.magnitude) if rpm else None,
            speed=int(speed.magnitude) if speed else None,
            coolant_temp=float(coolant_temp.magnitude) if coolant_temp else None,
            throttle_pos=float(throttle_pos.magnitude) if throttle_pos else None,
            maf=float(maf.magnitude) if maf else None,
            fuel_level=float(fuel_level.magnitude) if fuel_level else None,
            intake_temp=float(intake_temp.magnitude) if intake_temp else None,
            dtc_count=int(dtc_count) if dtc_count else None
        )
