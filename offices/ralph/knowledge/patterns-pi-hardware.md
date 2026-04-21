# Pi Hardware Patterns

Load on demand when working on Pi hardware layer (I2C, GPIO, UPS, display, pygame).

## Pi 5 Deployment Context

**Target deployment environment:**
- Hostname: chi-eclipse-01 (renamed from chi-eclipse-tuner Sprint 13 US-176; reboot persistence unconfirmed as of 2026-04-20)
- User: mcornelison, IP: 10.27.27.28
- Path: /home/mcornelison/Projects/Eclipse-01 (renamed from EclipseTuner during Sprint 13)
- Python 3.11+ in venv at ~/obd2-venv (NOT in project tree; survives project-tree wipes — see patterns-python-systems.md §systemd)
- Display: OSOYOO 3.5" HDMI (480x320) -- NOT GPIO/SPI
- Ollama: Remote on Chi-Srv-01 (10.27.27.10:11434), NEVER local on Pi
- WiFi: DeathStarWiFi (10.27.27.0/24 subnet)
- Bluetooth: OBDLink LX MAC 00:04:3E:85:0D:FB paired/bonded/trusted (see `scripts/pair_obdlink.sh` + `deploy/rfcomm-bind.service` from Sprint 14 US-196)

**Git branch: `main` is primary**
The project uses `main` as the primary branch (GitHub default). `master` has been deleted. Always work on/from `main`.

---

## Hardware Abstraction

**Pluggable reader pattern**
Use pluggable readers for hardware abstraction (GPIO, I2C, mock):
```python
def setVoltageReader(self, reader: Callable[[], Optional[float]]) -> None:
    self._voltageReader = reader

# Usage for GPIO ADC:
monitor.setVoltageReader(createAdcVoltageReader(channel=0))
# Usage for testing:
monitor.setVoltageReader(lambda: 12.5)
```

**Adafruit import handling**
Adafruit `board` module raises NotImplementedError on non-RPi - catch multiple exception types:
```python
try:
    import board
    from adafruit_rgb_display import st7789
    DISPLAY_AVAILABLE = True
except (ImportError, NotImplementedError, RuntimeError):
    DISPLAY_AVAILABLE = False
```

**Lazy hardware initialization**
Allow object creation on non-Pi for testing by deferring hardware init:
```python
def __init__(self, config):
    self._config = config
    self._i2cClient = None  # Lazy init

def _ensureInitialized(self):
    if self._i2cClient is None:
        self._i2cClient = I2cClient(self._config['bus'])
```

**HardwareManager integration order**
Initialize hardware after display (so display fallback available), shutdown before display:
```python
def _initializeAllComponents(self):
    self._initializeDisplay()      # First
    self._initializeHardwareManager()  # After display
    self._initializeDataComponents()

def _shutdownAllComponents(self):
    self._shutdownHardwareManager()  # Before display
    self._shutdownDisplay()          # Last
```

---

## I2C Communication

**I2C error codes - don't retry device-not-found**
OSError errno 121 = Remote I/O, 6 = ENXIO, 19 = ENODEV - these mean device not present, don't retry:
```python
NO_RETRY_ERRNOS = {6, 19, 121}
try:
    return self._bus.read_byte_data(address, register)
except OSError as e:
    if e.errno in NO_RETRY_ERRNOS:
        raise I2cDeviceNotFoundError(f"No device at 0x{address:02X}")
    raise I2cCommunicationError(str(e))  # Retryable
```

**Mocking smbus2 imports in tests**
Use patch.dict to mock hardware library imports:
```python
@patch.dict('sys.modules', {'smbus2': MagicMock()})
def test_i2c_client():
    from src.hardware.i2c_client import I2cClient
    # smbus2 is now mocked
```

**I2C context manager pattern**
Use context manager for automatic bus cleanup:
```python
class I2cClient:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()

# Usage
with I2cClient(bus=1) as client:
    voltage = client.readWord(0x36, 0x02)
```

**UPS signed 16-bit current**
UPS current register uses signed 16-bit: if raw > 32767, subtract 65536:
```python
rawCurrent = self._client.readWord(address, CURRENT_REGISTER)
if rawCurrent > 32767:
    rawCurrent -= 65536  # Convert to signed
return rawCurrent  # Positive = charging, negative = discharging
```

**Pi 5 PMIC EXT5V_V via vcgencmd is the AC-vs-battery signal when a HAT has no sense pin AND does not regulate the Pi-side rail**
The MAX17048 fuel gauge has no power-source register — it tracks the LiPo
cell only. On the X1209 there is no GPIO/I2C sense line for "is wall power
present". The Pi 5 PMIC exposes the USB-C EXT5V rail's voltage through
`vcgencmd pmic_read_adc EXT5V_V` (output format `EXT5V_V volt(24)=5.27558000V`).
When wall power is connected the reading is ~5.2V; on an unregulated HAT,
when unplugged (HAT boosting Pi from the UPS LiPo) it collapses well below 4.5V.

**CAVEAT (US-184 / I-015)**: the Geekworm X1209 SPECIFICALLY REGULATES the
Pi-side rail under UPS-boost, so EXT5V reads identical whether the wall
adapter is plugged in or not. **Do not use EXT5V as the source signal on
the X1209.** For regulated HATs use the VCELL-trend + CRATE-polarity
heuristic instead (see `offices/ralph/progress.txt` "VCELL-trend + CRATE"
pattern, and `src/pi/hardware/ups_monitor.py::getPowerSource` as the live
reference). EXT5V is still useful on the X1209 as a diagnostic
("is the HAT delivering power?") — see `getDiagnosticExt5vVoltage()`.

When the pattern below applies (unregulated passthrough HATs), it still
works; for any new HAT verify with a physical unplug drill before trusting
the datasheet on regulation behavior.

```python
def readExt5vVoltage() -> Optional[float]:
    try:
        result = subprocess.run(
            ['vcgencmd', 'pmic_read_adc', 'EXT5V_V'],
            capture_output=True, text=True, timeout=2.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    match = re.search(r'=\s*([\d.]+)\s*V', result.stdout)
    return float(match.group(1)) if match else None

EXT5V_EXTERNAL_THRESHOLD_V = 4.5
def derivePowerSource(v: Optional[float]) -> PowerSource:
    if v is None:
        return PowerSource.UNKNOWN
    return PowerSource.EXTERNAL if v >= EXT5V_EXTERNAL_THRESHOLD_V else PowerSource.BATTERY
```
Inject the reader callable at construction so tests can provide a deterministic
float without shelling out. Gracefully degrade on any failure to UNKNOWN (not
an exception) so shutdown logic can treat "no signal" as "don't act".
Established in `src/pi/hardware/ups_monitor.py` (US-180 Session 44).

**MAX17048 fuel gauge needs big-endian byte-swap over SMBus**
The Geekworm X1209 UPS HAT carries a MAX17048 fuel gauge at 0x36.
SMBus `read_word_data()` returns little-endian; MAX17048 stores every
16-bit register big-endian. Without byte-swap, a fully charged LiPo
reads as ~20V garbage instead of ~4.2V. Pattern:
```python
raw = bus.read_word_data(0x36, 0x02)         # VCELL
swap = ((raw & 0xFF) << 8) | ((raw >> 8) & 0xFF)
volts = swap * 78.125e-6                      # 78.125 µV/LSB
```
Key register map (authoritative — MAX17048 datasheet):
- 0x02 VCELL (RO word, 78.125 µV/LSB, big-endian)
- 0x04 SOC   (RO word; high byte = integer %, low byte = 1/256 %)
- 0x06 MODE  (WO — reads 0; do NOT treat as percentage byte)
- 0x08 VERSION (RO word; fingerprint the chip here)
- 0x0C CONFIG (RW word; boots to 0x971C family default)
- 0x16 CRATE (RO word, signed, 0.208 %/hr/LSB; may read 0xFFFF on variants)
The MAX17048 has **no current register** and **no power-source
register** — those must come from an external sense line or Pi 5 PMIC
(`vcgencmd pmic_read_adc EXT5V_V`). The existing
`src/pi/hardware/ups_monitor.py` register map (0x04=CURRENT, 0x06=%,
0x08=power_source) is fiction relative to this chip — see BL-005/TD-016
filed Session 41 for the in-flight remediation.

**Fingerprint an unknown I2C chip before trusting the code map**
Fastest way to confirm chip identity: read VERSION (MAX17048: 0x08)
with byte-swap, compare to datasheet. Next read CONFIG (0x0C) — boot
defaults are chip-specific. `smbus2.SMBus(1).read_word_data(addr, reg)`
from a one-liner takes <60s and catches register-map fiction that
would otherwise hide behind mocked tests for months.

---

## GPIO and gpiozero

**gpiozero Button configuration**
bounce_time for debounce, hold_time for long press:
```python
from gpiozero import Button
button = Button(
    pin=17,
    pull_up=True,        # Active low (button connects to GND)
    bounce_time=0.2,     # 200ms hardware debounce
    hold_time=3.0        # 3 seconds for long press
)
button.when_held = onLongPress
button.when_released = onShortPress
```

**gpiozero exception handling**
gpiozero raises multiple exception types on non-Pi:
```python
try:
    from gpiozero import Button
    GPIO_AVAILABLE = True
except (ImportError, RuntimeError, NotImplementedError):
    GPIO_AVAILABLE = False
```

---

## OSOYOO Display (HDMI)

**OSOYOO 3.5" is HDMI, NOT GPIO/SPI**
The project's display is HDMI-connected (480x320). Do NOT use Adafruit SPI display libraries (adafruit-circuitpython-rgb-display, blinka, lgpio). Pygame renders directly to the HDMI framebuffer:
```python
# This is how we drive the display - standard pygame to HDMI
import pygame
pygame.init()
screen = pygame.display.set_mode((480, 320))
```

---

## Pygame Display

**pygame exception handling on non-Pi**
pygame may raise RuntimeError on non-Pi systems:
```python
try:
    import pygame
    PYGAME_AVAILABLE = True
except (ImportError, RuntimeError):
    PYGAME_AVAILABLE = False
```

**pygame kiosk/embedded display**
Use NOFRAME and hide cursor for touch displays:
```python
pygame.init()
screen = pygame.display.set_mode((480, 320), pygame.NOFRAME)
pygame.mouse.set_visible(False)  # Hide cursor for touch
```

**Get local IP without network connection**
Use socket UDP connect trick:
```python
def getLocalIp() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))  # Doesn't actually send anything
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'
```

---

## System Telemetry

**CPU temperature on Raspberry Pi**
Value in /sys is millidegrees Celsius:
```python
def getCpuTemp() -> Optional[float]:
    try:
        with open('/sys/class/thermal/thermal_zone0/temp') as f:
            return int(f.read().strip()) / 1000.0  # Convert to Celsius
    except (FileNotFoundError, ValueError):
        return None
```

**Cross-platform disk space**
shutil.disk_usage works everywhere:
```python
import shutil
usage = shutil.disk_usage('/')
freeGb = usage.free / (1024**3)
```

**JSON serialization with datetime/enum**
Use default=str for automatic conversion:
```python
import json
data = {'timestamp': datetime.now(), 'status': SomeEnum.VALUE}
jsonStr = json.dumps(data, default=str)
```

---

## Display Patterns

**Double-buffering with PIL**
Use PIL Image for smooth display updates:
```python
image = Image.new('RGB', (240, 240), color=(0, 0, 0))
draw = ImageDraw.Draw(image)
draw.text((10, 10), "RPM: 3500", fill=(255, 255, 255))
display.image(image)  # Blit to hardware
```

**Color temperature ranges**
Standard temperature color coding for coolant:
```python
if temp < 60: color = BLUE      # Cold
elif temp < 100: color = WHITE  # Normal
elif temp < 110: color = ORANGE # Warm
else: color = RED               # Hot/Critical
```
