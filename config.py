# Default settings. The GUI reads these on startup; you can also edit them here.

STARTUP_DELAY = 5.0     # seconds to wait before driving (time to switch into Forza)
DRIVE_SECONDS = 180.0   # seconds to hold throttle per lap. SET THIS to your route's
                        # real length (a 44s test diverged from a ~3 min actual run).
TOTAL_MINUTES = 0.0     # total run time; 0 = run until you press Stop

# Smart screenshot recognition. Captures are in memory only and are not saved.
SMART_MENU_POLL_SECONDS = 0.75
SMART_RACE_EARLY_SECONDS = 10.0
SMART_RACE_EARLY_POLL_SECONDS = 2.0
SMART_RACE_POLL_SECONDS = 5.0
SMART_UNKNOWN_POLL_SECONDS = 1.0
SMART_DISCONNECT_RETRY_SECONDS = 2.0
SMART_DISCONNECT_MAX_RETRIES = 8

# Buy-car flow. Captures are in memory only and are not saved.
BUY_POLL_SECONDS = 0.75
BUY_ACTION_DELAY_SECONDS = 0.75
BUY_OCR_ENABLED = True
# Event-driven post-tap waits (speed-up): instead of always sleeping the fixed `after`, watch
# cheap downscaled frames and continue as soon as the screen has CHANGED then STABILISED,
# capped at `after` (so the worst case equals the old fixed wait -> no regression). Set
# BUY_EVENT_DRIVEN_WAITS=False to revert to the proven fixed sleeps. Thresholds are on a
# 0-255 grayscale mean-abs-diff of an ~80px-wide downscale; conservative defaults err toward
# waiting (animated/rotating-car screens never "stabilise" and simply wait the cap).
BUY_EVENT_DRIVEN_WAITS = True
BUY_SETTLE_FLOOR_SECONDS = 0.12     # min wait so the press registers before we read
BUY_SETTLE_POLL_SECONDS = 0.03      # cheap frame poll cadence (~30 Hz, no OCR)
BUY_SETTLE_CHANGE_THRESH = 6.0      # mean-abs-diff vs pre-tap that counts as "screen changed"
BUY_SETTLE_STABLE_THRESH = 2.0      # mean-abs-diff between consecutive frames that counts as "stable"
BUY_SETTLE_STABLE_FRAMES = 2        # consecutive stable frames required after a change
BUY_OCR_MIN_INTERVAL_SECONDS = 1.5
BUY_OCR_MIN_CONFIDENCE = 0.45
BUY_OCR_LOG_ITEMS = True
COMBO_EVENTLAB_FARM_SECONDS = 90 * 60  # one farming leg between buy-car cycles (default 1.5 hours)
COMBO_EVENTLAB_EXIT_MAX_OVERTIME = 15 * 60  # after total runtime, hard cap for waiting on the current race to finish
COMBO_EXIT_TO_PAUSE_MAX_ATTEMPTS = 8  # press A and try Menu this many times before giving up
COMBO_EXIT_TO_PAUSE_INITIAL_WAIT = 5.0  # pause after smart_runner exits before first attempt
COMBO_EXIT_TO_PAUSE_A_WAIT = 2.0  # pause between recovery A taps

# Restart-sequence timing (rarely needs changing):
MENU_DELAY = 0.6        # pause between menu button presses
LOAD_DELAY = 3.0        # wait for the event to reload before driving again
TAP_HOLD = 0.15         # how long each button press is held

# Optional keep-active helper:
GAME_TITLE = "Forza"    # window-title keyword used to find the game window
