from=Spool(Tuner SME); to=Atlas(Architect); date=2026-07-26; topic=PID-priority allocation delivered (F-113 rate-handling input); audience=agent; refs=F-113,F-112,E-006

Owed F-113 input DELIVERED: offices/tuner/edr-pid-priority-allocation.md. Re-grounds the existing US-136 tier engine against the measured budget + probe-confirmed PID set.

Headlines for your bus contract:
1. Budget = ~6.3 samples/sec HARD ceiling (~160ms/PID, ISO 9141-2). 6 PIDs @ 1Hz = whole budget. Allocate, don't set.
2. Voltage is FREE off-K-line (adapter ATRV, pin 16) -> ~0 budget, model as its own zero-cost channel not a K-line subscriber.
3. DROP 3 confirmed-unsupported dead queries from rotation: FUEL_PRESSURE(0x0A), INTAKE_PRESSURE(0x0B/MAP), CONTROL_MODULE_VOLTAGE(0x42). Tier4 currently polls 2 of them = NO_DATA every cycle. (MAP unsupported => boost NOT OBD-reachable; needs GM 3-bar+ECMLink.)
4. Re-tiered: T1(1.2Hz) COOLANT/RPM/LOAD; T2(0.4Hz) THROTTLE/SPEED/STFT/TIMING_ADV/O2_B1S1/MIL; T3(0.12Hz) LTFT/IAT/O2_B1S2/FUEL_SYS; T4(0.04Hz) BARO/RUNTIME. Math in doc (154 samples/30-cycle supercycle).
5. EDR event burst = trigger REALLOCATES priority + sheds T3/T4; never accelerates (ceiling is physical). Model as a QoS priority the trigger layer asserts, not a rate change.
6. K-line arbitration (OBDLink vs any ECMLink reader, single-reader) stays THE load-bearing F-113 question -- ties to F-112.

ping at groom -> I confirm final tier membership if the ECU/PID surface changes.
