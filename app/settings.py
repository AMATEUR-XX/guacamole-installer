import os
from pathlib import Path


APP_SESSION_SECRET = os.getenv("APP_SESSION_SECRET", "change-me-for-production")
GUACAMOLE_BASE_URL = os.getenv("GUACAMOLE_BASE_URL", "http://localhost:8080/guacamole")
TFTP_ROOT_PATH = Path(os.getenv("TFTP_ROOT_PATH", "./tftp_root")).resolve()
SER2NET_TELNET_TIMEOUT_SEC = float(os.getenv("SER2NET_TELNET_TIMEOUT_SEC", "3.0"))
ELTEX_USERNAME = os.getenv("ELTEX_USERNAME", "")
ELTEX_PASSWORD = os.getenv("ELTEX_PASSWORD", "")
ELTEX_ENABLE_PASSWORD = os.getenv("ELTEX_ENABLE_PASSWORD", "")
