import socket
import subprocess
import sys

# Function to test internet connection
def is_internet_connected(host="8.8.8.8", port=53, timeout=3):
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except Exception:
        return False

# Function to test if Bluetooth is on (Windows)
def is_bluetooth_on():
    try:
        # Windows: Use 'powershell' to check Bluetooth status
        cmd = [
            "powershell",
            "(Get-Service -Name bthserv).Status"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return "Running" in result.stdout
    except Exception:
        return False
