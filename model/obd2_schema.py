from dataclasses import dataclass
from typing import Optional

@dataclass
class OBD2StaticData:
    vin: Optional[str] = None
    calibration_id: Optional[str] = None
    ecu_name: Optional[str] = None
    fuel_type: Optional[str] = None
    engine_displacement: Optional[float] = None
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[str] = None
    body_class: Optional[str] = None
    engine_cylinders: Optional[str] = None
    engine_hp: Optional[str] = None
    plant_country: Optional[str] = None

@dataclass
class OBD2StreamingData:
    rpm: Optional[int] = None
    speed: Optional[int] = None
    coolant_temp: Optional[float] = None
    throttle_pos: Optional[float] = None
    maf: Optional[float] = None
    fuel_level: Optional[float] = None
    intake_temp: Optional[float] = None
    dtc_count: Optional[int] = None
    engine_load: Optional[float] = None
    fuel_trim_short_1: Optional[float] = None
    fuel_trim_long_1: Optional[float] = None
    fuel_trim_short_2: Optional[float] = None
    fuel_trim_long_2: Optional[float] = None
    o2_sensor_b1s1: Optional[float] = None
    o2_sensor_b1s2: Optional[float] = None
    intake_pressure: Optional[float] = None
    timing_advance: Optional[float] = None
    barometric_pressure: Optional[float] = None
    absolute_throttle_pos: Optional[float] = None
    battery_voltage: Optional[float] = None
    warmups_since_dtc_clear: Optional[int] = None
    distance_since_dtc_clear: Optional[int] = None
    fuel_pressure: Optional[float] = None
    evap_pressure: Optional[float] = None
    catalyst_temp_b1s1: Optional[float] = None
    catalyst_temp_b1s2: Optional[float] = None
    oil_temp: Optional[float] = None
    transmission_temp: Optional[float] = None
    ambient_air_temp: Optional[float] = None
    run_time: Optional[int] = None
    distance_mil_on: Optional[int] = None
    dtc_codes: Optional[str] = None
