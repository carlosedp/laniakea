"""Silence the firmware's serial log output.

Since v3.4 the Laniakea firmware prints ESP-IDF log messages on the USB-serial UART
(v3.3 printed almost nothing). This patch sets the global default log level
(esp_log default, initial value in .data) to 0 = ESP_LOG_NONE, so no app/IDF log
lines are sent. The 2nd-stage bootloader banner at power-on still prints.

Wave upload (MAGW/MAGD), flashing and esptool are unaffected: they don't use the log.
Note: `laniakea monitor` will show (almost) nothing with this patch.
"""

DESCRIPTION = "Silence serial logging (diagnostic for the v3.4+ menu clacking)"
OPTIONS = {"level": (0, "log level: 0 none, 1 error, 2 warn, 3 info (stock)")}
TARGETS = ["3.6"]


def apply(fw, level):
    addr, orig = fw.sym["log_level"]
    fw.write(addr, int(level).to_bytes(4, "little"), expect=orig)
    fw.tag("quiet" if level == 0 else f"log{level}")
