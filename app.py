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
DBC_PATH = "/home/jakerpi/e30-can-dash/dbc/Link_Generic_Dash.dbc"
ROTATE_DEG = 90
FPS = 30

# Gauge ranges
RPM_MIN,      RPM_MAX      = 0.0,   7100.0
BOOST_MIN,    BOOST_MAX    = -15.0,   12.0
OIL_MIN,      OIL_MAX      = 0.0,   120.0
FUEL_MIN,     FUEL_MAX     = 0.0,   120.0
LAMBDA_MIN,   LAMBDA_MAX   = 0.5,     2.0
IAT_MIN,      IAT_MAX      = -20.0, 100.0
TPS_MIN,      TPS_MAX      = 0.0,   100.0
BATT_MIN,     BATT_MAX     = 8.0,    16.0
MAP_MIN,      MAP_MAX      = 0.0,   300.0
SPARK_MIN,    SPARK_MAX    = -10.0,  60.0
ETHANOL_MIN,  ETHANOL_MAX  = 0.0,   100.0
DUTY_MIN,     DUTY_MAX     = 0.0,   100.0
AFR_MIN,      AFR_MAX      = 10.0,   20.0
KNOCK_MIN,    KNOCK_MAX    = 0.0,   100.0

KPA_TO_PSI = 0.1450377377

# ===== Colors =====
BLACK  = (0,   0,   0)
WHITE  = (255, 255, 255)
RED    = (220, 60,  60)
GRAY   = (120, 120, 120)
DGRAY  = (40,  40,  40)
LGRAY  = (200, 200, 200)
GREEN  = (80,  200, 80)
YELLOW = (220, 200, 60)
BLUE   = (60,  120, 220)
ORANGE = (220, 140, 40)

def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x

def fmt(v, digits=1):
    return "--" if v is None else f"{v:.{digits}f}"

def fmt_int(v):
    return "--" if v is None else f"{int(round(v))}"

# ===== Live Data =====
@dataclass
class LiveData:
    rpm:       float | None = None
    mgp_kpa:   float | None = None
    oil_kpa:   float | None = None
    fuel_kpa:  float | None = None
    lambda1:   float | None = None
    iat_c:     float | None = None
    tps:       float | None = None
    batt_v:    float | None = None
    map_kpa:   float | None = None
    spark:     float | None = None
    ethanol:   float | None = None
    duty:      float | None = None
    afr:       float | None = None
    knock:     float | None = None

    peak_rpm:   float | None = None
    peak_boost: float | None = None
    peak_oil:   float | None = None
    peak_fuel:  float | None = None

    lock: threading.Lock = field(default_factory=threading.Lock)

    def reset_peaks(self):
        with self.lock:
            self.peak_rpm   = None
            self.peak_boost = None
            self.peak_oil   = None
            self.peak_fuel  = None

    def update_peaks(self):
        with self.lock:
            boost = None if self.mgp_kpa is None else self.mgp_kpa * KPA_TO_PSI
            oil   = None if self.oil_kpa  is None else self.oil_kpa  * KPA_TO_PSI
            fuel  = None if self.fuel_kpa is None else self.fuel_kpa * KPA_TO_PSI

            if boost is not None:
                self.peak_boost = boost if self.peak_boost is None else max(self.peak_boost, boost)
            if oil is not None:
                self.peak_oil = oil if self.peak_oil is None else max(self.peak_oil, oil)
            if fuel is not None:
                self.peak_fuel = fuel if self.peak_fuel is None else max(self.peak_fuel, fuel)
            if self.rpm is not None:
                self.peak_rpm = self.rpm if self.peak_rpm is None else max(self.peak_rpm, self.rpm)

# ===== CAN Reader =====
class CanReader(threading.Thread):
    def __init__(self, data: LiveData):
        super().__init__(daemon=True)
        self.data = data
        self._stop = threading.Event()
        self.db = None
        try:
            self.db = cantools.database.load_file(DBC_PATH)
            print(f"DBC loaded OK — {len(self.db.messages)} messages")
        except Exception as e:
            print(f"DBC load failed: {e}")

    def stop(self):
        self._stop.set()

    def run(self):
        bus = None
        while not self._stop.is_set():
            try:
                try:
                    open(SERIAL_PATH, "rb").close()
                except FileNotFoundError:
                    time.sleep(0.5)
                    continue

                bus = can.interface.Bus(
                    interface="seeedstudio",
                    channel=SERIAL_PATH,
                    bitrate=CAN_BITRATE
                )

                while not self._stop.is_set():
                    msg = bus.recv(timeout=1.0)
                    if msg is None or self.db is None:
                        continue

                    try:
                        decoded = self.db.decode_message(msg.arbitration_id, msg.data)
                    except Exception:
                        continue

                    with self.data.lock:
                        d = decoded
                        if "Engine_Speed"    in d: self.data.rpm      = d["Engine_Speed"]
                        if "MGP"             in d: self.data.mgp_kpa  = d["MGP"]
                        if "Oil_Pressure"    in d: self.data.oil_kpa  = d["Oil_Pressure"]
                        if "Fuel_Pressure"   in d: self.data.fuel_kpa = d["Fuel_Pressure"]
                        if "Lambda_1"        in d: self.data.lambda1  = d["Lambda_1"]
                        if "IAT"             in d: self.data.iat_c    = d["IAT"]
                        if "TPS"             in d: self.data.tps      = d["TPS"]
                        if "Batt_Volts"      in d: self.data.batt_v   = d["Batt_Volts"]
                        if "MAP"             in d: self.data.map_kpa  = d["MAP"]
                        if "Ignition_Angle"  in d: self.data.spark    = d["Ignition_Angle"]
                        if "Ethanol_Content" in d: self.data.ethanol  = d["Ethanol_Content"]
                        if "Inj_Duty_Cycle"  in d: self.data.duty     = d["Inj_Duty_Cycle"]
                        if "AFR"             in d: self.data.afr      = d["AFR"]
                        if "Knock_Level"     in d: self.data.knock    = d["Knock_Level"]

                    self.data.update_peaks()

            except Exception as e:
                print(f"CAN error: {e}")
                time.sleep(0.5)
            finally:
                if bus:
                    try: bus.shutdown()
                    except: pass
                bus = None

# ===== Drawing helpers =====
def draw_text(surf, font, text, x, y, color=WHITE, center=False, topright=False):
    img = font.render(str(text), True, color)
    r = img.get_rect()
    if center:     r.center   = (x, y)
    elif topright: r.topright = (x, y)
    else:          r.topleft  = (x, y)
    surf.blit(img, r)

def draw_arc_gauge(surf, cx, cy, radius, value, vmin, vmax, color=RED):
    if value is None:
        return
    t = clamp((value - vmin) / (vmax - vmin), 0.0, 1.0)
    r = pygame.Rect(cx - radius, cy - radius, radius*2, radius*2)
    start_rad = math.radians(225 - 270*t)
    end_rad   = math.radians(225)
    try:
        pygame.draw.arc(surf, color, r, start_rad, end_rad, 6)
    except Exception:
        pass

def draw_gauge(surf, rect, label, value_raw, unit, peak_raw,
               vmin, vmax, big_font, med_font, small_font,
               digits=1, is_int=False, arc_color=RED):
    cx = rect.centerx
    cy = rect.centery
    radius = int(min(rect.width, rect.height) * 0.40)

    # Background
    pygame.draw.circle(surf, DGRAY,  (cx, cy), radius + 10, 10)
    pygame.draw.circle(surf, BLACK,  (cx, cy), radius +  2,  0)
    pygame.draw.circle(surf, GRAY,   (cx, cy), radius,       2)

    # Ticks
    for i in range(11):
        ang = math.radians(225 - 27*i)
        r1 = radius - 4
        r2 = radius - (16 if i%5==0 else 10)
        x1 = cx + math.cos(ang)*r1; y1 = cy - math.sin(ang)*r1
        x2 = cx + math.cos(ang)*r2; y2 = cy - math.sin(ang)*r2
        pygame.draw.line(surf, LGRAY if i%5==0 else GRAY, (x1,y1), (x2,y2),
                         2 if i%5==0 else 1)

    # Colored arc
    draw_arc_gauge(surf, cx, cy, radius - 5, value_raw, vmin, vmax, arc_color)

    # Needle
    if value_raw is not None:
        t = clamp((value_raw - vmin) / (vmax - vmin), 0.0, 1.0)
        ang = math.radians(225 - 270*t)
        nx = cx + math.cos(ang)*(radius - 28)
        ny = cy - math.sin(ang)*(radius - 28)
        pygame.draw.line(surf, WHITE, (cx, cy), (nx, ny), 3)
        pygame.draw.circle(surf, arc_color, (cx, cy), 5)

    # Label at top
    draw_text(surf, small_font, label, cx, rect.top + 8, center=True, color=LGRAY)

    # Peak value just below label in yellow
    pk_str = fmt_int(peak_raw) if is_int else fmt(peak_raw, digits)
    draw_text(surf, med_font, pk_str, cx, rect.top + 26, center=True, color=YELLOW)

    # Current value in center
    val_str = fmt_int(value_raw) if is_int else fmt(value_raw, digits)
    draw_text(surf, big_font, val_str, cx, cy - 14, center=True)

    # Unit
    draw_text(surf, small_font, unit, cx, cy + 22, center=True, color=GRAY)

# ===== Page 0 — Clock only =====
def draw_clock_page(surf, w, h, big_font, small_font):
    surf.fill(BLACK)
    cx, cy = w // 2, h // 2
    radius = int(min(w, h) * 0.34)

    pygame.draw.circle(surf, DGRAY, (cx, cy), radius + 14, 14)
    pygame.draw.circle(surf, BLACK, (cx, cy), radius +  6,  0)
    pygame.draw.circle(surf, GRAY,  (cx, cy), radius,       2)

    for i in range(60):
        ang = math.radians(90 - i*6)
        r1 = radius - (18 if i%5==0 else 10)
        x1 = cx + math.cos(ang)*r1;         y1 = cy - math.sin(ang)*r1
        x2 = cx + math.cos(ang)*(radius-2); y2 = cy - math.sin(ang)*(radius-2)
        col = WHITE if i%5==0 else GRAY
        pygame.draw.line(surf, col, (x1,y1), (x2,y2), 3 if i%5==0 else 1)

    now = datetime.now()
    sec    = now.second + now.microsecond / 1e6
    minute = now.minute + sec / 60.0
    hour   = (now.hour % 12) + minute / 60.0

    def hand(deg, length, width, color):
        ang = math.radians(90 - deg)
        x = cx + math.cos(ang)*length
        y = cy - math.sin(ang)*length
        pygame.draw.line(surf, color, (cx, cy), (int(x), int(y)), width)

    hand(hour*30.0,  radius*0.52, 7, LGRAY)
    hand(minute*6.0, radius*0.78, 5, LGRAY)
    hand(sec*6.0,    radius*0.88, 2, RED)
    pygame.draw.circle(surf, RED, (cx, cy), 6)


# ===== Page 1 — Main Gauges =====
def draw_gauges_page(surf, w, h, data: LiveData, big_font, med_font, small_font):
    surf.fill(BLACK)

    with data.lock:
        rpm       = data.rpm
        boost_psi = None if data.mgp_kpa  is None else data.mgp_kpa  * KPA_TO_PSI
        oil_psi   = None if data.oil_kpa  is None else data.oil_kpa  * KPA_TO_PSI
        fuel_psi  = None if data.fuel_kpa is None else data.fuel_kpa * KPA_TO_PSI
        batt      = data.batt_v
        p_rpm     = data.peak_rpm
        p_boost   = data.peak_boost
        p_oil     = data.peak_oil
        p_fuel    = data.peak_fuel

    pad = 16
    gw = (w - pad*3) // 2
    gh = (h - pad*3) // 2

    rects = [
        pygame.Rect(pad,       pad,       gw, gh),
        pygame.Rect(pad*2+gw,  pad,       gw, gh),
        pygame.Rect(pad,       pad*2+gh,  gw, gh),
        pygame.Rect(pad*2+gw,  pad*2+gh,  gw, gh),
    ]

    draw_gauge(surf, rects[0], "RPM",   rpm,       "rpm", p_rpm,   RPM_MIN,   RPM_MAX,   big_font, med_font, small_font, is_int=True, arc_color=RED)
    draw_gauge(surf, rects[1], "BOOST", boost_psi, "psi", p_boost, BOOST_MIN, BOOST_MAX, big_font, med_font, small_font, arc_color=BLUE)
    draw_gauge(surf, rects[2], "OIL",   oil_psi,   "psi", p_oil,   OIL_MIN,   OIL_MAX,   big_font, med_font, small_font, arc_color=ORANGE)
    draw_gauge(surf, rects[3], "FUEL",  fuel_psi,  "psi", p_fuel,  FUEL_MIN,  FUEL_MAX,  big_font, med_font, small_font, arc_color=GREEN)

    # Battery voltage top right
    batt_str = f"{fmt(batt, 2)}V"
    draw_text(surf, small_font, batt_str, w - 10, 10, topright=True, color=LGRAY)

# ===== Page 2 — Secondary Data List =====
def draw_data_page(surf, w, h, data: LiveData, med_font, small_font):
    surf.fill(BLACK)

    with data.lock:
        rows = [
            ("Lambda",   fmt(data.lambda1, 3), "λ"),
            ("Spark",    fmt(data.spark, 1),   "°"),
            ("IAT",      fmt(data.iat_c, 1),   "°C"),
            ("TPS",      fmt(data.tps, 1),     "%"),
            ("MAP",      fmt(data.map_kpa, 1), "kPa"),
            ("Ethanol",  fmt(data.ethanol, 1), "%"),
            ("Duty Cyc", fmt(data.duty, 1),    "%"),
            ("AFR",      fmt(data.afr, 2),     ""),
            ("Knock",    fmt(data.knock, 1),   "%"),
            ("Battery",  fmt(data.batt_v, 2),  "V"),
        ]

    col_w = w // 2
    row_h = (h - 40) // 5
    pad_x = 14

    for i, (label, value, unit) in enumerate(rows):
        col = i // 5
        row = i % 5
        x = col * col_w
        y = 20 + row * row_h

        if row > 0:
            pygame.draw.line(surf, DGRAY, (x + pad_x, y), (x + col_w - pad_x, y), 1)

        circ_cx = x + pad_x + 22
        circ_cy = y + row_h // 2
        pygame.draw.circle(surf, DGRAY, (circ_cx, circ_cy), 20, 0)
        pygame.draw.circle(surf, GRAY,  (circ_cx, circ_cy), 20, 2)
        draw_text(surf, small_font, value, circ_cx, circ_cy, center=True)

        draw_text(surf, small_font, label, x + pad_x + 50, circ_cy - 10, color=LGRAY)
        draw_text(surf, small_font, unit,  x + pad_x + 50, circ_cy + 6,  color=GRAY)

    pygame.draw.line(surf, DGRAY, (col_w, 20), (col_w, h - 20), 1)

def has_data(data: LiveData) -> bool:
    with data.lock:
        return any(v is not None for v in [data.rpm, data.mgp_kpa, data.oil_kpa])

# ===== Main =====
def main():
    pygame.init()
    pygame.mouse.set_visible(False)

    screen = pygame.display.set_mode((480, 640), pygame.FULLSCREEN)
    pygame.display.set_caption("E30 CAN Dash")

    w, h = 480, 640
    print(f"Screen size: {w}x{h}", flush=True)
    base = pygame.Surface((w, h)).convert()

    big_font   = pygame.font.Font(None, 84)
    med_font   = pygame.font.Font(None, 48)
    small_font = pygame.font.Font(None, 32)

    data   = LiveData()
    reader = CanReader(data)
    reader.start()

    # Fade-in: start black, reveal clock page over ~1 second
    screen.fill(BLACK)
    pygame.display.flip()
    draw_clock_page(base, w, h, big_font, small_font)
    overlay = pygame.Surface((w, h))
    overlay.fill(BLACK)
    fade_clock = pygame.time.Clock()
    for alpha in range(255, -1, -9):
        overlay.set_alpha(alpha)
        if ROTATE_DEG in (90, 180, 270):
            rot = pygame.transform.rotate(base, ROTATE_DEG)
            screen.fill(BLACK)
            screen.blit(rot, rot.get_rect(center=screen.get_rect().center))
        else:
            screen.blit(base, (0, 0))
        screen.blit(overlay, (0, 0))
        pygame.display.flip()
        fade_clock.tick(30)

    NUM_PAGES = 3
    page  = 0
    clock = pygame.time.Clock()

    down_pos  = None
    down_time = None
    moved     = 0.0

    running = True
    while running:
        clock.tick(FPS)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False

            elif event.type == pygame.MOUSEBUTTONDOWN:
                down_pos  = event.pos
                down_time = time.time()
                moved     = 0.0

            elif event.type == pygame.MOUSEMOTION and down_pos is not None:
                dx = event.pos[0] - down_pos[0]
                dy = event.pos[1] - down_pos[1]
                moved = max(moved, abs(dx) + abs(dy))

            elif event.type == pygame.MOUSEBUTTONUP and down_pos is not None:
                duration = time.time() - down_time
                dx = event.pos[0] - down_pos[0]
                dy = event.pos[1] - down_pos[1]

                if duration >= 1.0 and moved < 40:
                    data.reset_peaks()
                elif abs(dx) > w * 0.20 and abs(dx) > abs(dy):
                    page = (page + (1 if dx < 0 else -1)) % NUM_PAGES

                down_pos  = None
                down_time = None
                moved     = 0.0

            elif event.type == pygame.FINGERDOWN:
                # display_rotate=1 rotates 90°; remap raw touch → screen coords
                down_pos  = (event.y * 480, (1.0 - event.x) * 640)
                down_time = time.time()
                moved     = 0.0

            elif event.type == pygame.FINGERMOTION and down_pos is not None:
                dx = event.y * 480 - down_pos[0]
                dy = (1.0 - event.x) * 640 - down_pos[1]
                moved = max(moved, abs(dx) + abs(dy))

            elif event.type == pygame.FINGERUP and down_pos is not None:
                duration = time.time() - down_time
                dx = event.y * 480 - down_pos[0]
                dy = (1.0 - event.x) * 640 - down_pos[1]

                if duration >= 1.0 and moved < 40:
                    data.reset_peaks()
                elif abs(dx) > w * 0.20 and abs(dx) > abs(dy):
                    page = (page + (1 if dx < 0 else -1)) % NUM_PAGES

                down_pos  = None
                down_time = None
                moved     = 0.0

        if page == 0:
            draw_clock_page(base, w, h, big_font, small_font)
        elif page == 1:
            draw_gauges_page(base, w, h, data, big_font, med_font, small_font)
        else:
            draw_data_page(base, w, h, data, med_font, small_font)

        if not has_data(data):
            nd = small_font.render("NO DATA", True, RED)
            base.blit(nd, (10, h - 30))

        if ROTATE_DEG in (90, 180, 270):
            rot = pygame.transform.rotate(base, ROTATE_DEG)
            screen.fill(BLACK)
            screen.blit(rot, rot.get_rect(center=screen.get_rect().center))
        else:
            screen.blit(base, (0, 0))

        pygame.display.flip()

    reader.stop()
    reader.join(timeout=1.0)
    pygame.quit()

if __name__ == "__main__":
    main()
