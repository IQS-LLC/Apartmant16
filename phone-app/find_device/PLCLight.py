import pyads
import time
import random

# ═══════════════════════════════════════════════════════════
#  FADE MAP
#  Maps the string sent by Flutter → integer written to
#  GVL.nFadeTime (Tc3_DALI.E_DALIFadeTime enum value).
#
#  TwinCAT Tc3_DALI fade-time enum:
#    0  → 0 ms  (instant / no fade)   ← T22600ms.0  = 0
#    1  → 0.7 s                        ← T22600ms.1
#    2  → 1.0 s                        ← T22600ms.2
#    3  → 1.4 s                        ← T22600ms.3
#    4  → 2.0 s  (default)             ← T22600ms.4
#    5  → 2.8 s                        ← T22600ms.5
#    6  → 4.0 s                        ← T22600ms.6
#    7  → 5.7 s                        ← T22600ms.7
#    8  → 8.0 s                        ← T22600ms.8
#
#  Flutter sends: '0ms' | '500ms' | '1000ms' | '2000ms' | '5000ms'
#  We map to the closest valid DALI fade-time enum index.
# ═══════════════════════════════════════════════════════════
FADE_MAP = {
    '0ms':    0,   # instant snap  → enum 0  (0 ms)
    '500ms':  1,   # ~0.7 s        → enum 1  (closest below)
    '1000ms': 2,   # ~1.0 s        → enum 2
    '2000ms': 4,   # ~2.0 s        → enum 4
    '5000ms': 7,   # ~5.7 s        → enum 7  (closest above)
}
DEFAULT_FADE_VAL = 4  # 2.0 s


class PLCLight:
    def __init__(self, netid, ip, mock=False):
        self.netid = netid
        self.ip    = ip
        self.plc   = None
        self.mock  = mock
        self.mock_state = {
            'level':        0,
            'fade_time':    4,
            'system_ready': True,
            'light_error':  False,
            'button1':      False,
            'button2':      False,
            'light_on':     False,   # tracks GVL.bLightOn for mock
        }

    # ───────────────────────────────
    #  CONNECTION
    # ───────────────────────────────
    def connect(self):
        if self.mock:
            print("Mock PLC connected")
            return self
        try:
            self.plc = pyads.Connection(self.netid, pyads.PORT_TC3PLC1, self.ip)
            self.plc.open()
            print("Real PLC connected")
            return self
        except Exception as e:
            print(f"Real PLC connection failed: {e}, falling back to mock mode")
            self.mock = True
            return self

    def disconnect(self):
        if not self.mock and self.plc:
            self.plc.close()

    # ───────────────────────────────
    #  INTERNAL TRIGGER
    #  Pulses GVL.bLightTrigger FALSE→TRUE→FALSE.
    #  POU_Control watches this with an IF and fires
    #  fbDirect (DirectArcPowerControl) to set the level.
    # ───────────────────────────────
    def _trigger(self):
        if self.mock:
            time.sleep(0.1)
            return
        self.plc.write_by_name('GVL.bLightTrigger', False, pyads.PLCTYPE_BOOL)
        time.sleep(0.1)
        self.plc.write_by_name('GVL.bLightTrigger', True,  pyads.PLCTYPE_BOOL)
        time.sleep(0.3)
        self.plc.write_by_name('GVL.bLightTrigger', False, pyads.PLCTYPE_BOOL)
        time.sleep(0.2)

    # ───────────────────────────────
    #  FORCE INITIALIZE
    #
    #  After a CX restart the DALI function block (fbDimmer /
    #  fbDirect) is cold.  The POU_Lights ladder uses:
    #    rtAppLight : R_TRIG on GVL.bLightOn
    #  so the app-side dimmer path only fires on a rising edge
    #  of bLightOn (FALSE → TRUE transition).
    #
    #  Without a physical button press that edge never happens,
    #  leaving the DALI bus uninitialized and the app silent.
    #
    #  This method replicates the button press sequence:
    #    1. Write nDimLevel to a safe non-zero value (last or 50%)
    #    2. Ensure bLightOn is FALSE  (clears any stale TRUE)
    #    3. Set bLightOn = TRUE       → rising edge → rtAppLight fires
    #    4. Wait one PLC cycle (≥50 ms, fbDimmer.tCycleActualLevel)
    #    5. Fire _trigger() so fbDirect also picks up the level
    #    6. Leave bLightOn TRUE (bus is now warm)
    #
    #  Call this from the /plc/init/ endpoint when the user
    #  taps "Initialize" in the app.
    # ───────────────────────────────
    def force_initialize(self, percent=50):
        percent = max(1, min(100, percent))   # never initialize to 0
        if self.mock:
            self.mock_state['light_on']    = False
            self.mock_state['level']       = int((percent / 100) * 254)
            time.sleep(0.05)
            self.mock_state['light_on']    = True
            self.mock_state['system_ready'] = True
            time.sleep(0.1)
            self._trigger()
            return True

        level = int((percent / 100) * 254)

        # Step 1 — pre-load the target level
        self.plc.write_by_name('GVL.nDimLevel', level, pyads.PLCTYPE_BYTE)

        # Step 2 — ensure bLightOn starts FALSE so the edge is clean
        self.plc.write_by_name('GVL.bLightOn', False, pyads.PLCTYPE_BOOL)
        time.sleep(0.05)

        # Step 3 — rising edge → rtAppLight fires → fbDirect gets bStart
        self.plc.write_by_name('GVL.bLightOn', True, pyads.PLCTYPE_BOOL)
        time.sleep(0.1)   # one PLC cycle is 50 ms; give it two

        # Step 4 — also fire the direct-arc trigger so POU_Control path runs
        self._trigger()

        return True

    # ───────────────────────────────
    #  SET BRIGHTNESS
    # ───────────────────────────────
    def set_brightness(self, percent):
        percent = max(0, min(100, percent))
        if self.mock:
            self.mock_state['level'] = int((percent / 100) * 254)
            self._trigger()
            return
        level = int((percent / 100) * 254)
        self.plc.write_by_name('GVL.nDimLevel', level, pyads.PLCTYPE_BYTE)
        self._trigger()

    # ───────────────────────────────
    #  SET FADE TIME
    #  Accepts an integer ms value (already resolved from the
    #  FADE_MAP in views.py) OR a legacy string key for backwards
    #  compat.  Writes the DALI enum index to GVL.nFadeTime.
    # ───────────────────────────────
    def set_fade_time(self, fade_input):
        # Accept either an integer (ms from views.py FADE_MAP)
        # or a legacy string key for backwards compatibility.
        if isinstance(fade_input, int):
            val = FADE_MAP.get(f'{fade_input}ms', DEFAULT_FADE_VAL)
        else:
            val = FADE_MAP.get(str(fade_input), DEFAULT_FADE_VAL)

        if self.mock:
            self.mock_state['fade_time'] = val
            return
        self.plc.write_by_name('GVL.nFadeTime', val, pyads.PLCTYPE_USINT)

    def on(self):
        self.set_brightness(100)

    def off(self):
        self.set_brightness(0)

    # ───────────────────────────────
    #  READ STATE
    #
    #  GVL.bLightError is fbDimmer.bError — the DALI ballast
    #  error output from FB_DALI102Dimmer1Switch.  It is TRUE
    #  when the KL6821 reports a DALI bus fault (ballast not
    #  responding, short circuit, power supply error, etc.).
    #
    #  On a fresh CX restart fbDimmer hasn't finished
    #  initialising so bError can sit TRUE until the DALI bus
    #  is warmed up.  The app shows this honestly; use
    #  force_initialize() to clear it.
    # ───────────────────────────────
    def read_state(self):
        if self.mock:
            if random.random() < 0.05:
                self.mock_state['button1'] = not self.mock_state['button1']
            if random.random() < 0.03:
                self.mock_state['button2'] = not self.mock_state['button2']
            return {
                'actual_percent': round((self.mock_state['level'] / 254) * 100),
                'system_ready':   self.mock_state['system_ready'],
                'light_error':    self.mock_state['light_error'],
                'button1':        self.mock_state['button1'],
                'button2':        self.mock_state['button2'],
            }

        actual = self.plc.read_by_name('GVL.nActualLevel',     pyads.PLCTYPE_BYTE)
        ready  = self.plc.read_by_name('GVL.bSystemReady',     pyads.PLCTYPE_BOOL)
        error  = self.plc.read_by_name('GVL.bLightError',      pyads.PLCTYPE_BOOL)
        btn1   = self.plc.read_by_name('GVL.bSwitchChannel1',  pyads.PLCTYPE_BOOL)
        btn2   = self.plc.read_by_name('GVL.bSwitchChannel2',  pyads.PLCTYPE_BOOL)
        return {
            'actual_percent': round((actual / 254) * 100),
            'system_ready':   ready,
            'light_error':    error,
            'button1':        btn1,
            'button2':        btn2,
        }

    def __enter__(self):
        return self.connect()

    def __exit__(self, *args):
        self.disconnect()