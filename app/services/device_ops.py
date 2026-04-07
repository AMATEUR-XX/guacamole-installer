from datetime import datetime
from pathlib import Path
import re
import telnetlib

from app.models import Device
from app.settings import (
    ELTEX_ENABLE_PASSWORD,
    ELTEX_PASSWORD,
    ELTEX_USERNAME,
    SER2NET_TELNET_TIMEOUT_SEC,
    TFTP_ROOT_PATH,
)

TFTP_ROOT = Path(TFTP_ROOT_PATH)
TFTP_ROOT.mkdir(exist_ok=True)


def apply_config_to_device(device: Device, config_text: str) -> str:
    # MVP: сохраняем выгруженный конфиг как артефакт задания для устройства.
    file_name = f"{device.name}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.cfg"
    file_path = TFTP_ROOT / file_name
    file_path.write_text(config_text, encoding="utf-8")
    return f"Config queued for {device.name} via TFTP artifact {file_name}"


def fetch_running_config(device: Device) -> str:
    try:
        return _fetch_running_config_via_ser2net(device)
    except Exception as exc:
        # Fallback to MVP sample if serial endpoint is unreachable.
        return (
            f"! WARNING: ser2net fetch failed ({exc})\n"
            f"hostname {device.name}\n"
            "interface vlan 1\n"
            " ip address 10.10.10.1 255.255.255.0\n"
            " no shutdown\n"
            "!\n"
            "router ospf 1\n"
            " network 10.10.10.0 0.0.0.255 area 0\n"
        )


def _wait_prompt(tn: telnetlib.Telnet) -> bytes:
    return tn.read_until(b"#", timeout=SER2NET_TELNET_TIMEOUT_SEC)


def _fetch_running_config_via_ser2net(device: Device) -> str:
    tn = telnetlib.Telnet(device.host, int(device.port), timeout=SER2NET_TELNET_TIMEOUT_SEC)
    try:
        banner = tn.read_until(b":", timeout=SER2NET_TELNET_TIMEOUT_SEC)
        lower_banner = banner.lower()
        if b"login" in lower_banner or b"username" in lower_banner:
            if not ELTEX_USERNAME:
                raise RuntimeError("ELTEX_USERNAME is not set")
            tn.write((ELTEX_USERNAME + "\n").encode())
            passwd_prompt = tn.read_until(b":", timeout=SER2NET_TELNET_TIMEOUT_SEC).lower()
            if b"password" in passwd_prompt:
                if not ELTEX_PASSWORD:
                    raise RuntimeError("ELTEX_PASSWORD is not set")
                tn.write((ELTEX_PASSWORD + "\n").encode())

        tn.write(b"terminal length 0\n")
        _wait_prompt(tn)

        tn.write(b"show running-config\n")
        raw = tn.read_until(b"#", timeout=SER2NET_TELNET_TIMEOUT_SEC * 2).decode("utf-8", errors="ignore")

        # Remove ANSI/terminal control symbols and command echo noise.
        cleaned = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", raw)
        cleaned = cleaned.replace("\r", "")
        lines = [line for line in cleaned.split("\n") if line.strip()]
        if lines and lines[0].strip().lower().startswith("show running-config"):
            lines = lines[1:]
        config = "\n".join(lines)
        if not config:
            raise RuntimeError("Empty running-config from device")

        # Optional privileged mode support for platforms that require it.
        if ">" in raw and ELTEX_ENABLE_PASSWORD:
            tn.write(b"enable\n")
            tn.read_until(b":", timeout=SER2NET_TELNET_TIMEOUT_SEC)
            tn.write((ELTEX_ENABLE_PASSWORD + "\n").encode())
        return config
    finally:
        try:
            tn.write(b"exit\n")
        except Exception:
            pass
        tn.close()
