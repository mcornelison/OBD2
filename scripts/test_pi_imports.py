"""Quick import test for Pi dependencies."""
import sys

tests = [
    ("Python version", lambda: sys.version),
    ("sqlite3", lambda: __import__("sqlite3").sqlite_version),
    ("PIL/Pillow", lambda: __import__("PIL.Image", fromlist=["Image"]).__version__),
    ("pygame", lambda: __import__("pygame").ver),
    ("obd", lambda: __import__("obd").__version__),
    ("RPi.GPIO", lambda: __import__("RPi.GPIO").VERSION),
    ("board (blinka)", lambda: str(__import__("board"))),
    ("adafruit_rgb_display", lambda: str(__import__("adafruit_rgb_display.st7789", fromlist=["st7789"]))),
    ("gpiozero", lambda: __import__("gpiozero").__version__),
    ("smbus2", lambda: __import__("smbus2").__version__),
    ("dotenv", lambda: __import__("dotenv").__version__),
]

for name, test in tests:
    try:
        result = test()
        print(f"  PASS  {name}: {result}")
    except Exception as e:
        print(f"  FAIL  {name}: {type(e).__name__}: {e}")
