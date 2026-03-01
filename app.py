import math
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime

import pygame

import can
import cantools

# ===== User config =====
SERIAL_PATH = "/dev/serial/by-path/platform-3f980000.usb-usb-0:1.1:1.0-port0"
CAN_BITRATE = 1_000_000
DBC_PATH = "/home/jakerpi/dash/dbc/Link_Generic_Dash.dbc"

# If you rotate the OS display, leave this 0.
# If you want to rotate in-app (slower), set to 90 or 270.
ROTATE_DEG = 0  # 0 / 90 / 180 / 270

FPS = 30

# Gauge ranges (tune later)
BOOST_PSI_MIN, BOOST_PSI_MAX = -15.0, 40.0
OIL_PSI_MIN, OIL_PSI_MAX = 0.0, 120.0
FUEL_PSI_MIN, FUEL_PSI_MAX = 0.0, 120.0
RPM_MIN, RPM_MAX = 0.0, 8000.0

# ===== Helpers =====
KPA_TO_PSI = 0.1450377377

def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x

def fmt_num(v, digits=1):
    if v is None:
        return "--"
    return f"{v:.{digits}f}"

def fmt_int(v):
    if v is None:
        return "--"
    return f"{int(round(v))}"

@dataclass
class LiveData:
    rpm: float | None = None
    mgp_kpa: float | None = None
    oil_kpa: float | None = None
    fuel_kpa: float | None = None
    batt_v: float | None = None

    peak_boost_psi: float | None = None
    peak_oil_psi: float | None = None
    peak_fuel_psi: float | None = None
    peak_rpm: float | None = None

    lock: threading.Lock = field(default_factory=threading.Lock)

    def reset_peaks(self):
        with self.lock:
            self.peak_boost_psi = None
            self.peak_oil_psi = None
            self.peak_fuel_psi = None
            self.peak_rpm = None

    def update_peaks(self):
        with self.lock:
            boost_psi = None if self.mgp_kpa is None else (self.mgp_kpa * KPA_TO_PSI)
            oil_psi = None if self.oil_kpa is None else (self.oil_kpa * KPA_TO_PSI)
            fuel_psi = None if self.fuel_kpa is None else (self.fuel_kpa * KPA_TO_PSI)

            if boost_psi is not None:
                self.peak_boost_psi = boost_psi if self.peak_boost_psi is None else max(self.peak_boost_psi, boost_psi)
            if oil_psi is not None:
                self.peak_oil_psi = oil_psi if self.peak_oil_psi is None else max(self.peak_oil_psi, oil_psi)
            if fuel_psi is not None:
                self.peak_fuel_psi = fuel_psi if self.peak_fuel_psi is None else max(self.peak_fuel_psi, fuel_psi)
            if self.rpm is not None:
                self.peak_rpm = self.rpm if self.peak_rpm is None else max(self.peak_rpm, self.rpm)

class CanReader(threading.Thread):
    def __init__(self, data: LiveData):
        super().__init__(daemon=True)
        self.data = data
        self._stop = threading.Event()
        self.db = None

        try:
            self.db = cantools.database.load_file(DBC_PATH)
        except Exception as e:
            print(f"DBC load failed: {e}")
            self.db = None

    def stop(self):
        self._stop.set()

    def run(self):
        bus = None
        while not self._stop.is_set():
            try:
                # Wait for adapter path to exist (handles USB resets / ttyUSB renumbering)
                try:
                    open(SERIAL_PATH, "rb").close()
                except FileNotFoundError:
                    time.sleep(0.5)
                    continue

                bus = can.interface.Bus(interface="seeedstudio", channel=SERIAL_PATH, bitrate=CAN_BITRATE)

                while not self._stop.is_set():
                    msg = bus.recv(timeout=1.0)
                    if msg is None:
                        continue
                    if msg.arbitration_id != 0x3E8:
                        continue

                    if self.db is None:
                        continue

                    try:
                        decoded = self.db.decode_message(msg.arbitration_id, msg.data)
                    except Exception:
                        continue

                    with self.data.lock:
                        # Signal names from your DBC:
                        # Engine_Speed, MGP, Oil_Pressure, Fuel_Pressure, Batt_Volts
                        self.data.rpm = decoded.get("Engine_Speed", self.data.rpm)
                        self.data.mgp_kpa = decoded.get("MGP", self.data.mgp_kpa)
                        self.data.oil_kpa = decoded.get("Oil_Pressure", self.data.oil_kpa)
                        self.data.fuel_kpa = decoded.get("Fuel_Pressure", self.data.fuel_kpa)
                        self.data.batt_v = decoded.get("Batt_Volts", self.data.batt_v)

                    self.data.update_peaks()

            except Exception as e:
                print(f"CAN read error: {e}")
                time.sleep(0.5)
            finally:
                if bus is not None:
                    try:
                        bus.shutdown()
                    except Exception:
                        pass
                bus = None

# ===== UI drawing =====
def draw_text(surf, font, text, x, y, color=(255,255,255), center=False):
    img = font.render(text, True, color)
    r = img.get_rect()
    if center:
        r.center = (x, y)
    else:
        r.topleft = (x, y)
    surf.blit(img, r)

def draw_gauge(surf, rect, label, value, unit, peak, vmin, vmax, big_font, small_font):
    cx = rect.centerx
    cy = rect.centery
    radius = int(min(rect.width, rect.height) * 0.42)

    # ring
    pygame.draw.circle(surf, (40,40,40), (cx, cy), radius+10, 10)
    pygame.draw.circle(surf, (10,10,10), (cx, cy), radius+2, 0)
    pygame.draw.circle(surf, (60,60,60), (cx, cy), radius, 2)

    # ticks
    for i in range(0, 11):
        ang = math.radians(225 - (270 * (i/10)))
        x1 = cx + math.cos(ang) * (radius - 8)
        y1 = cy - math.sin(ang) * (radius - 8)
        x2 = cx + math.cos(ang) * (radius - 22)
        y2 = cy - math.sin(ang) * (radius - 22)
        pygame.draw.line(surf, (120,120,120), (x1,y1), (x2,y2), 2)

    # needle
    if value is not None:
        t = (value - vmin) / (vmax - vmin) if vmax != vmin else 0.0
        t = clamp(t, 0.0, 1.0)
        deg = 225 - (270 * t)
        ang = math.radians(deg)
        nx = cx + math.cos(ang) * (radius - 30)
        ny = cy - math.sin(ang) * (radius - 30)
        pygame.draw.line(surf, (220,60,60), (cx,cy), (nx,ny), 4)
        pygame.draw.circle(surf, (220,60,60), (cx,cy), 6)

    # labels
    draw_text(surf, small_font, label, cx, rect.top + 10, center=True)
    val_str = fmt_int(value) if label == "RPM" else fmt_num(value, 1)
    draw_text(surf, big_font, val_str, cx, cy - 10, center=True)
    draw_text(surf, small_font, unit, cx, cy + 28, center=True)

    peak_str = "--" if peak is None else (fmt_int(peak) if label == "RPM" else fmt_num(peak, 1))
    draw_text(surf, small_font, f"peak {peak_str}", cx, rect.bottom - 28, center=True)

def draw_clock_page(surf, w, h, big_font, small_font):
    surf.fill((0,0,0))
    cx, cy = w//2, h//2
    radius = int(min(w,h) * 0.35)

    # face
    pygame.draw.circle(surf, (20,20,20), (cx,cy), radius+14, 14)
    pygame.draw.circle(surf, (0,0,0), (cx,cy), radius+6, 0)
    pygame.draw.circle(surf, (80,80,80), (cx,cy), radius, 2)

    # ticks
    for i in range(60):
        ang = math.radians(90 - (i*6))
        r1 = radius - (18 if i%5==0 else 10)
        r2 = radius - 2
        x1 = cx + math.cos(ang)*r1
        y1 = cy - math.sin(ang)*r1
        x2 = cx + math.cos(ang)*r2
        y2 = cy - math.sin(ang)*r2
        col = (220,220,220) if i%5==0 else (120,120,120)
        pygame.draw.line(surf, col, (x1,y1), (x2,y2), 3 if i%5==0 else 1)

    now = datetime.now()
    sec = now.second + now.microsecond/1e6
    minute = now.minute + sec/60.0
    hour = (now.hour % 12) + minute/60.0

    # hands
    def hand(angle_deg, length, width, color):
        ang = math.radians(90 - angle_deg)
        x = cx + math.cos(ang)*length
        y = cy - math.sin(ang)*length
        pygame.draw.line(surf, color, (cx,cy), (x,y), width)

    hand(hour*30.0, radius*0.55, 7, (220,220,220))
    hand(minute*6.0, radius*0.80, 5, (220,220,220))
    hand(sec*6.0, radius*0.90, 2, (220,60,60))
    pygame.draw.circle(surf, (220,60,60), (cx,cy), 6)

    # small digital time (bottom)
    draw_text(surf, big_font, now.strftime("%H:%M"), cx, cy + radius + 40, center=True)
    draw_text(surf, small_font, "Swipe to gauges", cx, h - 30, center=True)

def draw_gauges_page(surf, w, h, data: LiveData, big_font, small_font):
    surf.fill((0,0,0))

    with data.lock:
        rpm = data.rpm
        mgp_kpa = data.mgp_kpa
        oil_kpa = data.oil_kpa
        fuel_kpa = data.fuel_kpa
        batt = data.batt_v

        boost_psi = None if mgp_kpa is None else (mgp_kpa * KPA_TO_PSI)
        oil_psi = None if oil_kpa is None else (oil_kpa * KPA_TO_PSI)
        fuel_psi = None if fuel_kpa is None else (fuel_kpa * KPA_TO_PSI)

        p_boost = data.peak_boost_psi
        p_oil = data.peak_oil_psi
        p_fuel = data.peak_fuel_psi
        p_rpm = data.peak_rpm

    pad = 18
    gw = (w - pad*3)//2
    gh = (h - pad*3)//2

    rects = [
        pygame.Rect(pad, pad, gw, gh),
        pygame.Rect(pad*2+gw, pad, gw, gh),
        pygame.Rect(pad, pad*2+gh, gw, gh),
        pygame.Rect(pad*2+gw, pad*2+gh, gw, gh),
    ]

    draw_gauge(surf, rects[0], "BOOST", boost_psi, "psi", p_boost, BOOST_PSI_MIN, BOOST_PSI_MAX, big_font, small_font)
    draw_gauge(surf, rects[1], "OIL", oil_psi, "psi", p_oil, OIL_PSI_MIN, OIL_PSI_MAX, big_font, small_font)
    draw_gauge(surf, rects[2], "FUEL", fuel_psi, "psi", p_fuel, FUEL_PSI_MIN, FUEL_PSI_MAX, big_font, small_font)
    draw_gauge(surf, rects[3], "RPM", rpm, "rpm", p_rpm, RPM_MIN, RPM_MAX, big_font, small_font)

    # battery top-right
    batt_str = "--" if batt is None else f"{batt:.2f}V"
    draw_text(surf, small_font, f"Batt {batt_str}", w - 10, 8, center=False)
    # right align:
    img = small_font.render(f"Batt {batt_str}", True, (255,255,255))
    surf.blit(img, img.get_rect(topright=(w-10, 8)))

    # hint bottom
    draw_text(surf, small_font, "Hold 1s to reset peaks", w//2, h-22, center=True)

def main():
    pygame.init()
    pygame.mouse.set_visible(False)

    # Fullscreen on whatever the current framebuffer/window is
    screen = pygame.display.set_mode((0,0), pygame.FULLSCREEN)
    pygame.display.set_caption("E30 CAN Dash")

    w, h = screen.get_size()
    base = pygame.Surface((w, h)).convert()

    big_font = pygame.font.Font(None, 84)
    small_font = pygame.font.Font(None, 32)

    data = LiveData()
    reader = CanReader(data)
    reader.start()

    page = 0
    clock = pygame.time.Clock()

    down_pos = None
    down_time = None
    moved = 0.0

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False

            elif event.type == pygame.MOUSEBUTTONDOWN:
                down_pos = event.pos
                down_time = time.time()
                moved = 0.0

            elif event.type == pygame.MOUSEMOTION and down_pos is not None:
                dx = event.pos[0] - down_pos[0]
                dy = event.pos[1] - down_pos[1]
                moved = max(moved, abs(dx) + abs(dy))

            elif event.type == pygame.MOUSEBUTTONUP and down_pos is not None and down_time is not None:
                up_pos = event.pos
                duration = time.time() - down_time
                dx = up_pos[0] - down_pos[0]
                dy = up_pos[1] - down_pos[1]

                # Long press to reset peaks (minimal movement)
                if duration >= 1.0 and moved < 40:
                    data.reset_peaks()
                else:
                    # Swipe to change page
                    if abs(dx) > (w * 0.20) and abs(dx) > abs(dy):
                        if dx < 0:
                            page = (page + 1) % 2
                        else:
                            page = (page - 1) % 2

                down_pos = None
                down_time = None
                moved = 0.0

        if page == 0:
            draw_clock_page(base, w, h, big_font, small_font)
        else:
            draw_gauges_page(base, w, h, data, big_font, small_font)

        if ROTATE_DEG in (90, 180, 270):
            rot = pygame.transform.rotate(base, ROTATE_DEG)
            # Center it (size changes on 90/270)
            r = rot.get_rect(center=screen.get_rect().center)
            screen.fill((0,0,0))
            screen.blit(rot, r)
        else:
            screen.blit(base, (0,0))

        pygame.display.flip()

    reader.stop()
    reader.join(timeout=1.0)
    pygame.quit()

if __name__ == "__main__":
    main()
