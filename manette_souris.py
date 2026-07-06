# -*- coding: utf-8 -*-
"""
Manette -> Souris + clavier virtuel navigable
Aucune dépendance externe : ctypes (XInput + SendInput) + tkinter.

Mapping général :
  Stick gauche   : déplacer le curseur
  Stick droit    : molette (vertical + horizontal)
  A              : clic gauche (maintien possible pour glisser-déposer)
  B              : clic droit
  X              : clic milieu
  Y              : ouvrir/fermer le clavier virtuel
  RB (maintenu)  : souris lente (précision)
  LB (maintenu)  : souris rapide
  START + BACK   : quitter le programme

Quand le clavier est ouvert :
  Croix (flèches): sélectionner une touche (cadre bleu)
  A              : appuyer sur la touche sélectionnée
  X              : effacer (retour arrière)
  B              : espace
  START + stick gauche : déplacer le clavier à l'écran
  BACK + stick droit   : redimensionner le clavier
  Les sticks continuent de piloter la souris et la molette.

Disposition : détectée automatiquement depuis Windows (AZERTY/QWERTY/QWERTZ).
La touche en haut à droite du clavier virtuel permet d'en changer, ou :
  python manette_souris.py azerty|qwerty|qwertz
"""

import ctypes
import ctypes.wintypes as wt
import math
import queue
import threading
import time
import tkinter as tk

# ---------------------------------------------------------------- XInput ---

for dll in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
    try:
        _xinput = ctypes.windll.LoadLibrary(dll)
        break
    except OSError:
        _xinput = None
if _xinput is None:
    raise SystemExit("XInput introuvable : manette Xbox/compatible requise.")


class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", wt.WORD),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", wt.DWORD), ("Gamepad", XINPUT_GAMEPAD)]


BTN_DPAD_UP, BTN_DPAD_DOWN, BTN_DPAD_LEFT, BTN_DPAD_RIGHT = 0x1, 0x2, 0x4, 0x8
BTN_START, BTN_BACK = 0x10, 0x20
BTN_LB, BTN_RB = 0x100, 0x200
BTN_A, BTN_B, BTN_X, BTN_Y = 0x1000, 0x2000, 0x4000, 0x8000

DEADZONE_L = 7849
DEADZONE_R = 8689

# -------------------------------------------------------------- SendInput ---


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wt.LONG),
        ("dy", wt.LONG),
        ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD),
        ("wScan", wt.WORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]

    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _U)]


INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x0020, 0x0040
MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x0800, 0x1000
KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0002, 0x0004

VK = {
    "BACKSPACE": 0x08, "TAB": 0x09, "ENTER": 0x0D, "ESC": 0x1B,
    "SPACE": 0x20, "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28,
    "DELETE": 0x2E, "WIN": 0x5B,
}

_user32 = ctypes.windll.user32


def _send_mouse(dx=0, dy=0, data=0, flags=0):
    inp = INPUT(type=INPUT_MOUSE)
    inp.mi = MOUSEINPUT(int(dx), int(dy), data & 0xFFFFFFFF, flags, 0, None)
    _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def mouse_move(dx, dy):
    _send_mouse(dx, dy, flags=MOUSEEVENTF_MOVE)


def mouse_wheel(delta, horizontal=False):
    _send_mouse(data=delta, flags=MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL)


def send_vk(vk):
    """Frappe une touche virtuelle (down + up)."""
    for flags in (0, KEYEVENTF_KEYUP):
        inp = INPUT(type=INPUT_KEYBOARD)
        inp.ki = KEYBDINPUT(vk, 0, flags, 0, None)
        _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def send_char(ch):
    """Envoie un caractère Unicode, indépendant de la disposition clavier."""
    for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
        inp = INPUT(type=INPUT_KEYBOARD)
        inp.ki = KEYBDINPUT(0, ord(ch), flags, 0, None)
        _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


# ------------------------------------------------------- Clavier virtuel ---

# Une touche = (étiquette, action, largeur en colonnes)
# action : caractère à taper, nom VK (en MAJUSCULES dans VK), ou commande
# spéciale "SHIFT" / "PAGE" / "LAYOUT".
K = lambda label, action=None, span=1: (label, action if action is not None else label, span)

# Rangées de lettres par disposition (la rangée du bas reçoit ⇧ et ⌫ autour)
LAYOUTS = {
    "AZERTY": ("azertyuiop", "qsdfghjklm", "wxcvbn'"),
    "QWERTY": ("qwertyuiop", "asdfghjkl", "zxcvbnm'"),
    "QWERTZ": ("qwertzuiop", "asdfghjkl", "yxcvbnm'"),
}
LAYOUT_ORDER = list(LAYOUTS)


def detect_layout():
    """Disposition par défaut d'après le clavier détecté par Windows."""
    hwnd = _user32.GetForegroundWindow()
    tid = _user32.GetWindowThreadProcessId(hwnd, None)
    _user32.GetKeyboardLayout.restype = ctypes.c_void_p
    hkl = _user32.GetKeyboardLayout(tid) or 0
    lang = hkl & 0x3FF  # langue principale du LANGID
    if lang == 0x0C:    # français (France, Belgique, Suisse...)
        return "AZERTY"
    if lang == 0x07:    # allemand
        return "QWERTZ"
    return "QWERTY"


def build_pages(layout_name):
    r1, r2, r3 = LAYOUTS[layout_name]
    lettres = [
        [K(c) for c in "1234567890"] + [K(layout_name, "LAYOUT", 2)],
        [K(c) for c in r1],
        [K(c) for c in r2],
        [K("⇧", "SHIFT")] + [K(c) for c in r3] + [K("⌫", "BACKSPACE", 2)],
        [K("&123", "PAGE", 2), K(","), K("Espace", "SPACE", 3), K("."), K("◀", "LEFT"), K("▶", "RIGHT"), K("Entrée", "ENTER", 2)],
    ]
    symboles = [
        [K("é"), K("è"), K("ê"), K("ë"), K("à"), K("â"), K("ç"), K("ù"), K("û"), K("î")],
        [K("ô"), K("œ"), K("&"), K('"'), K("("), K(")"), K("-"), K("_"), K("="), K("+")],
        [K("@"), K("#"), K("€"), K("$"), K("%"), K("*"), K("/"), K("\\"), K(":"), K(";")],
        [K("<"), K(">"), K("["), K("]"), K("{"), K("}"), K("!"), K("?"), K("⌫", "BACKSPACE", 2)],
        [K("abc", "PAGE", 2), K(","), K("Espace", "SPACE", 3), K("."), K("◀", "LEFT"), K("▶", "RIGHT"), K("Entrée", "ENTER", 2)],
    ]
    return lettres, symboles

# Rappel du raccourci manette sur certaines touches : lettre cerclée (glyphe
# Unicode, donc lissée par la police), affichée à côté de l'étiquette.
BADGES = {
    "BACKSPACE": "Ⓧ",
    "SPACE": "Ⓑ",
}

COL_BG = "#1e1e1e"
COL_KEY = "#333333"
COL_KEY_SPECIAL = "#2a2a2a"
COL_SEL = "#0a84ff"
COL_TXT = "#f0f0f0"
KEY_W, KEY_H, GAP = 58, 52, 5


class VirtualKeyboard:
    def __init__(self, root, layout_name=None):
        self.root = root
        self.visible = False
        self.page = 0
        self.shift = False
        self.row, self.col = 1, 4  # démarre au centre de la 1re rangée de lettres
        self.win = None
        self.scale = 1.0  # facteur de taille (BACK + stick droit)
        self.set_layout(layout_name or detect_layout())

    def _size(self):
        """Dimensions courantes : (touche_l, touche_h, espacement, fenêtre_l, fenêtre_h)."""
        kw = max(20, round(KEY_W * self.scale))
        kh = max(18, round(KEY_H * self.scale))
        gap = max(2, round(GAP * self.scale))
        cols = 12  # largeur logique de la grille
        return kw, kh, gap, cols * kw + (cols + 1) * gap, 5 * kh + 6 * gap

    def set_layout(self, name):
        self.layout_name = name
        self.pages = build_pages(name)
        print(f"Disposition du clavier : {name}")

    # ---- fenêtre ----

    def toggle(self):
        self.hide() if self.visible else self.show()

    def show(self):
        if self.win is None:
            self._create_window()
        self.win.deiconify()
        self.visible = True
        self._render()

    def hide(self):
        if self.win is not None:
            self.win.withdraw()
        self.visible = False

    def _create_window(self):
        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=COL_BG)
        self.win.withdraw()

        _, _, _, w, h = self._size()
        # Zone de travail (au-dessus de la barre des tâches)
        rect = wt.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
        self.pos = [rect.left + (rect.right - rect.left - w) // 2,
                    rect.bottom - h - 12]
        self.win.geometry(f"{w}x{h}+{self.pos[0]}+{self.pos[1]}")

        # WS_EX_NOACTIVATE : la fenêtre ne prend jamais le focus,
        # le texte part donc toujours dans l'application active.
        self.win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(self.win.winfo_id()) or self.win.winfo_id()
        GWL_EXSTYLE = -20
        WS_EX_NOACTIVATE, WS_EX_TOPMOST = 0x08000000, 0x00000008
        style = ctypes.windll.user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOPMOST)

        self.canvas = tk.Canvas(self.win, bg=COL_BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._on_click)

    def nudge(self, dx, dy):
        """Déplace la fenêtre du clavier (START + stick gauche)."""
        if self.win is None:
            return
        # borné à l'écran virtuel (tous moniteurs confondus)
        vx = _user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
        vy = _user32.GetSystemMetrics(77)
        vw = _user32.GetSystemMetrics(78)
        vh = _user32.GetSystemMetrics(79)
        w, h = self.win.winfo_width(), self.win.winfo_height()
        self.pos[0] = max(vx, min(vx + vw - w, self.pos[0] + dx))
        self.pos[1] = max(vy, min(vy + vh - h, self.pos[1] + dy))
        self.win.geometry(f"+{self.pos[0]}+{self.pos[1]}")

    def rescale(self, delta):
        """Redimensionne le clavier (BACK + stick droit), centre conservé."""
        if self.win is None:
            return
        old = self.scale
        self.scale = max(0.5, min(2.5, self.scale * (1.0 + delta)))
        if self.scale == old:
            return
        prev_w, prev_h = self.win.winfo_width(), self.win.winfo_height()
        _, _, _, w, h = self._size()
        self.pos[0] += (prev_w - w) // 2
        self.pos[1] += (prev_h - h) // 2
        self.win.geometry(f"{w}x{h}+{self.pos[0]}+{self.pos[1]}")
        self.nudge(0, 0)  # re-borne à l'écran
        self._render()

    # ---- rendu ----

    def _layout(self):
        return self.pages[self.page]

    def _label(self, key):
        label, action, _ = key
        if self.shift and len(action) == 1 and action.isalpha():
            return label.upper()
        return label

    def _render(self):
        c = self.canvas
        c.delete("all")
        self.hitboxes = []  # (x1, y1, x2, y2, r, i)
        rows = self._layout()
        kw, kh, gap, total_w, _ = self._size()
        for r, row in enumerate(rows):
            row_cols = sum(k[2] for k in row)
            row_w = row_cols * kw + (len(row) - 1) * gap
            x = (total_w - row_w) // 2
            y = gap + r * (kh + gap)
            for i, key in enumerate(row):
                label, action, span = key
                w = span * kw
                sel = (r == self.row and i == self.col)
                special = len(action) > 1  # touche de commande
                fill = COL_SEL if sel else (COL_KEY_SPECIAL if special else COL_KEY)
                if action == "SHIFT" and self.shift and not sel:
                    fill = "#555c66"
                c.create_rectangle(x, y, x + w, y + kh, fill=fill,
                                   outline="#ffffff" if sel else "", width=2)
                text = self._label(key)
                font = ("Segoe UI", max(7, round((12 if len(text) > 4 else 15) * self.scale)))
                if action in BADGES:
                    text += "  " + BADGES[action]
                c.create_text(x + w / 2, y + kh / 2, text=text,
                              fill=COL_TXT, font=font)
                self.hitboxes.append((x, y, x + w, y + kh, r, i))
                x += w + gap

    # ---- navigation / frappe ----

    def move(self, dr, dc):
        rows = self._layout()
        if dr:
            self.row = max(0, min(len(rows) - 1, self.row + dr))
        self.col = max(0, min(len(rows[self.row]) - 1, self.col + dc))
        self._render()

    def press_selected(self):
        rows = self._layout()
        self._press(rows[self.row][min(self.col, len(rows[self.row]) - 1)])

    def _on_click(self, event):
        for x1, y1, x2, y2, r, i in getattr(self, "hitboxes", []):
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                self.row, self.col = r, i
                self.press_selected()
                return

    def _press(self, key):
        _, action, _ = key
        if action == "SHIFT":
            self.shift = not self.shift
        elif action == "LAYOUT":
            i = LAYOUT_ORDER.index(self.layout_name)
            self.set_layout(LAYOUT_ORDER[(i + 1) % len(LAYOUT_ORDER)])
        elif action == "PAGE":
            self.page = 1 - self.page
            self.row = min(self.row, len(self._layout()) - 1)
            self.col = min(self.col, len(self._layout()[self.row]) - 1)
        elif action in VK:
            send_vk(VK[action])
        else:
            ch = action.upper() if (self.shift and action.isalpha()) else action
            send_char(ch)
            if self.shift:       # shift « une frappe » comme sur téléphone
                self.shift = False
        self._render()


# ------------------------------------------------------------------ Boucle ---

POLL_HZ = 1000       # fréquence de lecture de la manette (thread dédié)
BASE_SPEED = 1600.0  # vitesse max du curseur en pixels/seconde
SLOW_FACTOR = 0.25   # avec RB
FAST_FACTOR = 2.2    # avec LB
SCROLL_SPEED = 4200.0  # unités molette max par seconde (120 = 1 cran)
RESIZE_SPEED = 1.2   # vitesse de redimensionnement du clavier (échelle/s)
REPEAT_DELAY = 0.35  # délai avant répétition de la croix (s)
REPEAT_RATE = 0.09   # intervalle de répétition (s)


def stick(value, deadzone):
    """Normalise un axe [-32768..32767] -> [-1..1] avec zone morte et courbe."""
    if abs(value) < deadzone:
        return 0.0
    v = (abs(value) - deadzone) / (32767.0 - deadzone)
    v = v * v  # courbe quadratique : précis au centre, rapide au bord
    return math.copysign(min(v, 1.0), value)


class App:
    def __init__(self, layout_name=None):
        self.root = tk.Tk()
        self.root.withdraw()
        self.kb = VirtualKeyboard(self.root, layout_name)
        self.state = XINPUT_STATE()
        self.prev_buttons = 0
        self.connected = False
        self.acc = [0.0, 0.0, 0.0, 0.0]  # x, y, molette, molette horizontale
        self.left_held = self.right_held = self.mid_held = False
        self.dpad_next = {}  # bit -> prochain instant de répétition
        self.retry_at = 0.0  # limite les sondages quand pas de manette
        self.last_packet = None  # dwPacketNumber : ne traiter que les changements
        self.running = True
        self.kb_shown = False  # miroir de kb.visible, lisible depuis le thread
        self.ui_queue = queue.Queue()
        self.win_move = [0.0, 0.0]  # déplacement du clavier accumulé (START+stick)
        self.win_resize = 0.0       # redimensionnement accumulé (BACK+stick droit)

    def run(self):
        print(__doc__)
        print(f"Polling manette : {POLL_HZ} Hz (thread dédié)")
        print("En attente d'une manette... (START+BACK ou Ctrl+C pour quitter)")
        threading.Thread(target=self.gamepad_loop, daemon=True).start()
        self.root.after(20, self.pump_ui)
        try:
            self.root.mainloop()
        finally:
            self.running = False

    def gamepad_loop(self):
        """Thread temps réel : lecture manette + souris, sans passer par tkinter."""
        ctypes.windll.winmm.timeBeginPeriod(1)
        k32 = ctypes.windll.kernel32
        period = 1.0 / POLL_HZ

        # Timer périodique haute résolution (Windows 10 1803+) : cadence 1 ms
        # exacte sans busy-wait. time.sleep() plafonne vers ~600 Hz.
        CREATE_WAITABLE_TIMER_HIGH_RESOLUTION = 0x00000002
        TIMER_ALL_ACCESS = 0x1F0003
        k32.CreateWaitableTimerExW.restype = ctypes.c_void_p
        timer = k32.CreateWaitableTimerExW(None, None,
                                           CREATE_WAITABLE_TIMER_HIGH_RESOLUTION,
                                           TIMER_ALL_ACCESS)
        if timer:
            due = ctypes.c_longlong(-1)  # démarre tout de suite (unités 100 ns)
            ok = k32.SetWaitableTimer(ctypes.c_void_p(timer), ctypes.byref(due),
                                      max(1, round(1000 / POLL_HZ)),  # période en ms
                                      None, None, False)
            if not ok:
                k32.CloseHandle(ctypes.c_void_p(timer))
                timer = None

        last = time.monotonic()
        try:
            while self.running:
                now = time.monotonic()
                dt = min(now - last, 0.05)  # borne en cas de gel du système
                last = now
                self.tick(now, dt)
                if timer:
                    k32.WaitForSingleObject(ctypes.c_void_p(timer), 10)
                else:
                    time.sleep(period)
        finally:
            if timer:
                k32.CloseHandle(ctypes.c_void_p(timer))
            ctypes.windll.winmm.timeEndPeriod(1)

    def pump_ui(self):
        """Thread tkinter : applique les actions clavier envoyées par le thread manette."""
        try:
            while True:
                action, *args = self.ui_queue.get_nowait()
                if action == "toggle":
                    self.kb.toggle()
                elif action == "move":
                    self.kb.move(*args)
                elif action == "press":
                    self.kb.press_selected()
                elif action == "quit":
                    self.root.destroy()
                    return
        except queue.Empty:
            pass
        # déplacement du clavier accumulé par le thread manette (coalescé ici)
        mdx, mdy = int(self.win_move[0]), int(self.win_move[1])
        if (mdx or mdy) and self.kb.visible:
            self.win_move[0] -= mdx
            self.win_move[1] -= mdy
            self.kb.nudge(mdx, mdy)
        rs, self.win_resize = self.win_resize, 0.0
        if abs(rs) > 0.001 and self.kb.visible:
            self.kb.rescale(rs)
        self.root.after(20, self.pump_ui)

    def tick(self, now, dt):
        if not self.connected and now < self.retry_at:
            return
        if _xinput.XInputGetState(0, ctypes.byref(self.state)) != 0:
            if self.connected:
                print("Manette déconnectée.")
                self.connected = False
            self.retry_at = now + 1.0  # sonder 1x/s quand pas de manette
            return
        if not self.connected:
            print("Manette connectée : c'est parti !")
            self.connected = True

        pad = self.state.Gamepad
        btn = pad.wButtons

        # Se caler sur le polling de la manette : dwPacketNumber n'avance que si
        # l'état a changé. On ne traite rien tant qu'il est stable, SAUF si un
        # stick est incliné (le curseur doit continuer à bouger) ou si la croix
        # est maintenue clavier ouvert (répétition de touche).
        sticks_active = (abs(pad.sThumbLX) >= DEADZONE_L or abs(pad.sThumbLY) >= DEADZONE_L
                         or abs(pad.sThumbRX) >= DEADZONE_R or abs(pad.sThumbRY) >= DEADZONE_R)
        dpad_held = self.kb_shown and btn & 0xF
        if (self.state.dwPacketNumber == self.last_packet
                and not sticks_active and not dpad_held):
            return
        self.last_packet = self.state.dwPacketNumber

        pressed = btn & ~self.prev_buttons
        released = ~btn & self.prev_buttons

        if btn & BTN_START and btn & BTN_BACK:
            print("Arrêt demandé (START+BACK).")
            self.running = False
            self.ui_queue.put(("quit",))
            return

        # ---- souris (toujours active), vitesses en unités/seconde ----
        speed = BASE_SPEED * dt
        if btn & BTN_RB:
            speed *= SLOW_FACTOR
        elif btn & BTN_LB:
            speed *= FAST_FACTOR

        sx = stick(pad.sThumbLX, DEADZONE_L) * speed
        sy = -stick(pad.sThumbLY, DEADZONE_L) * speed
        if self.kb_shown and btn & BTN_START:
            # START + stick gauche : déplacer le clavier au lieu du curseur
            self.win_move[0] += sx
            self.win_move[1] += sy
        else:
            self.acc[0] += sx
            self.acc[1] += sy
            dx, dy = int(self.acc[0]), int(self.acc[1])
            if dx or dy:
                mouse_move(dx, dy)
                self.acc[0] -= dx
                self.acc[1] -= dy

        if self.kb_shown and btn & BTN_BACK:
            # BACK + stick droit : redimensionner le clavier (haut = agrandir)
            self.win_resize += stick(pad.sThumbRY, DEADZONE_R) * RESIZE_SPEED * dt
        else:
            self.acc[2] += stick(pad.sThumbRY, DEADZONE_R) * SCROLL_SPEED * dt
            self.acc[3] += stick(pad.sThumbRX, DEADZONE_R) * SCROLL_SPEED * dt
        w, hw = int(self.acc[2]), int(self.acc[3])
        if w:
            mouse_wheel(w)
            self.acc[2] -= w
        if hw:
            mouse_wheel(hw, horizontal=True)
            self.acc[3] -= hw

        # ---- clavier virtuel (rendu délégué au thread tkinter via la file) ----
        if pressed & BTN_Y:
            self.kb_shown = not self.kb_shown
            self.ui_queue.put(("toggle",))

        if self.kb_shown:
            for bit, (dr, dc) in ((BTN_DPAD_UP, (-1, 0)), (BTN_DPAD_DOWN, (1, 0)),
                                  (BTN_DPAD_LEFT, (0, -1)), (BTN_DPAD_RIGHT, (0, 1))):
                if pressed & bit:
                    self.ui_queue.put(("move", dr, dc))
                    self.dpad_next[bit] = now + REPEAT_DELAY
                elif btn & bit and now >= self.dpad_next.get(bit, now + 1):
                    self.ui_queue.put(("move", dr, dc))
                    self.dpad_next[bit] = now + REPEAT_RATE

            if pressed & BTN_A:
                self.ui_queue.put(("press",))
            if pressed & BTN_X:
                send_vk(VK["BACKSPACE"])
            if pressed & BTN_B:
                send_vk(VK["SPACE"])
        else:
            # clics (down/up séparés pour permettre le glisser-déposer)
            if pressed & BTN_A:
                _send_mouse(flags=MOUSEEVENTF_LEFTDOWN)
                self.left_held = True
            if pressed & BTN_B:
                _send_mouse(flags=MOUSEEVENTF_RIGHTDOWN)
                self.right_held = True
            if pressed & BTN_X:
                _send_mouse(flags=MOUSEEVENTF_MIDDLEDOWN)
                self.mid_held = True

        # les relâchements de clic sont traités même si le clavier vient
        # de s'ouvrir, pour ne jamais laisser un bouton « coincé »
        if released & BTN_A and self.left_held:
            _send_mouse(flags=MOUSEEVENTF_LEFTUP)
            self.left_held = False
        if released & BTN_B and self.right_held:
            _send_mouse(flags=MOUSEEVENTF_RIGHTUP)
            self.right_held = False
        if released & BTN_X and self.mid_held:
            _send_mouse(flags=MOUSEEVENTF_MIDDLEUP)
            self.mid_held = False

        self.prev_buttons = btn


if __name__ == "__main__":
    import sys

    layout = None
    if len(sys.argv) > 1:
        arg = sys.argv[1].upper()
        if arg in LAYOUTS:
            layout = arg
        else:
            raise SystemExit(f"Disposition inconnue : {sys.argv[1]} (choix : {', '.join(LAYOUTS)})")
    try:
        App(layout).run()
    except KeyboardInterrupt:
        pass
