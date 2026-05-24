"""Lightweight Forza UI state detection from in-memory frames.

The detector intentionally uses layout/color cues instead of account names,
car names, or OCR. This keeps it fast and more portable across machines.
"""
from dataclasses import dataclass


STATE_PRESTART = "prestart"
STATE_PRESTART_WRONG_SELECTION = "prestart_wrong_selection"
STATE_RACING = "racing"
STATE_RESULTS = "results"
STATE_CONFIRM_RESTART = "confirm_restart"
STATE_CONTROLLER_DISCONNECTED = "controller_disconnected"
STATE_PAUSE_MENU = "pause_menu"
STATE_UNKNOWN = "unknown"


def _lime(r, g, b):
    return g >= 190 and r >= 135 and b <= 95 and (g - b) >= 120


def _white(r, g, b):
    return r >= 210 and g >= 210 and b >= 210


def _dark(r, g, b):
    return r <= 55 and g <= 55 and b <= 55


def _gray_bar(r, g, b):
    return 55 <= r <= 135 and 55 <= g <= 135 and 55 <= b <= 135


def _teal(r, g, b):
    return 15 <= r <= 95 and 90 <= g <= 190 and 85 <= b <= 190 and g >= r + 35


@dataclass
class Detection:
    state: str
    confidence: float
    scores: dict


class ForzaScreenDetector:
    """Detect the automation states shown in the user's reference images."""

    def detect(self, frame):
        scores = {
            "confirm_lime": frame.ratio((0.32, 0.40, 0.68, 0.50), _lime, step=5),
            "confirm_dark": frame.ratio((0.32, 0.50, 0.68, 0.66), _dark, step=7),
            "modal_lime": frame.ratio((0.30, 0.42, 0.70, 0.56), _lime, step=5),
            "modal_dark_body": frame.ratio((0.30, 0.50, 0.70, 0.66), _dark, step=7),
            "modal_white_option": frame.ratio((0.30, 0.60, 0.70, 0.70), _white, step=5),
            "disconnect_lime": frame.ratio((0.30, 0.44, 0.70, 0.55), _lime, step=5),
            "disconnect_dark": frame.ratio((0.30, 0.55, 0.70, 0.66), _dark, step=7),
            "disconnect_blur_mid": frame.ratio((0.18, 0.22, 0.82, 0.82), self._blurred_modal_bg, step=10),
            "results_lime": frame.ratio((0.16, 0.22, 0.84, 0.34), _lime, step=6),
            "results_dark": frame.ratio((0.16, 0.28, 0.84, 0.86), _dark, step=8),
            "prestart_lime": frame.ratio((0.02, 0.58, 0.28, 0.73), _lime, step=5),
            "prestart_dark": frame.ratio((0.02, 0.58, 0.28, 0.88), _dark, step=8),
            "prestart_row0_lime": frame.ratio((0.02, 0.61, 0.28, 0.675), _lime, step=4),
            "prestart_row1_lime": frame.ratio((0.02, 0.675, 0.28, 0.725), _lime, step=4),
            "prestart_row2_lime": frame.ratio((0.02, 0.725, 0.28, 0.775), _lime, step=4),
            "prestart_row3_lime": frame.ratio((0.02, 0.775, 0.28, 0.825), _lime, step=4),
            "prestart_row4_lime": frame.ratio((0.02, 0.825, 0.28, 0.88), _lime, step=4),
            "pause_teal": frame.ratio((0.02, 0.08, 0.98, 0.90), _teal, step=12),
            "pause_left_white": frame.ratio((0.12, 0.30, 0.30, 0.82), _white, step=8),
            "pause_right_white": frame.ratio((0.72, 0.30, 0.90, 0.82), _white, step=8),
            "pause_left_lime": frame.ratio((0.15, 0.35, 0.27, 0.55), _lime, step=5),
            "pause_right_lime": frame.ratio((0.75, 0.35, 0.88, 0.55), _lime, step=5),
            "pause_tab_white": frame.ratio((0.30, 0.22, 0.72, 0.30), _white, step=8),
            "race_white_hud": frame.ratio((0.02, 0.04, 0.22, 0.18), _white, step=5),
            "race_gray_hud": frame.ratio((0.02, 0.10, 0.22, 0.20), _gray_bar, step=5),
        }
        scores["prestart_other_lime"] = max(
            scores["prestart_row1_lime"],
            scores["prestart_row2_lime"],
            scores["prestart_row3_lime"],
            scores["prestart_row4_lime"],
        )
        scores["prestart_any_lime"] = max(
            scores["prestart_lime"],
            scores["prestart_row0_lime"],
            scores["prestart_other_lime"],
        )
        scores["pause_white_tiles"] = min(scores["pause_left_white"], scores["pause_right_white"])
        scores["pause_lime_icons"] = scores["pause_left_lime"] + scores["pause_right_lime"]

        # Center modal.图4 has a white option row; controller-disconnected has a
        # simpler body with no white option row. This avoids OCR/text matching.
        if scores["modal_lime"] >= 0.05:
            if scores["modal_white_option"] >= 0.08 and scores["modal_dark_body"] >= 0.02:
                return Detection(STATE_CONFIRM_RESTART, min(0.99, scores["modal_lime"] * 6), scores)
            if (
                scores["disconnect_lime"] >= 0.12
                and scores["modal_white_option"] < 0.03
                and scores["disconnect_blur_mid"] >= 0.10
            ):
                return Detection(
                    STATE_CONTROLLER_DISCONNECTED,
                    min(0.99, scores["disconnect_lime"] * 3),
                    scores,
                )
        if scores["modal_lime"] >= 0.05 and scores["modal_dark_body"] >= 0.06:
            return Detection(
                STATE_CONTROLLER_DISCONNECTED,
                min(0.99, scores["modal_lime"] * 6),
                scores,
            )

        # Results screen: wide lime leaderboard/header plus mostly dark table.
        if scores["results_lime"] >= 0.055 and scores["results_dark"] >= 0.42:
            return Detection(STATE_RESULTS, min(0.99, scores["results_lime"] * 8), scores)

        # Pause hub: teal background, large white tiles, and the lime menu icons.
        if (
            scores["pause_teal"] >= 0.16
            and scores["pause_white_tiles"] >= 0.28
            and scores["pause_lime_icons"] >= 0.055
            and scores["pause_tab_white"] >= 0.12
        ):
            return Detection(
                STATE_PAUSE_MENU,
                min(0.97, max(scores["pause_teal"], scores["pause_white_tiles"]) * 2),
                scores,
            )

        # Pre-race menu: only press A when the first row is the selected lime item.
        # If the lime selection is on another row, let the runner move upward first.
        if scores["prestart_any_lime"] >= 0.018 and scores["prestart_dark"] >= 0.20:
            if scores["prestart_other_lime"] < 0.018:
                return Detection(STATE_PRESTART, min(0.95, scores["prestart_any_lime"] * 14), scores)
            if scores["prestart_other_lime"] >= 0.018:
                return Detection(
                    STATE_PRESTART_WRONG_SELECTION,
                    min(0.90, scores["prestart_other_lime"] * 14),
                    scores,
                )

        # Race HUD: white progress/time text plus the gray time strip in top-left.
        # Requiring both prevents bright sky or helper-window backgrounds from being
        # mistaken for the in-race HUD.
        if scores["race_white_hud"] >= 0.025 and scores["race_gray_hud"] >= 0.012:
            return Detection(
                STATE_RACING,
                min(0.95, max(scores["race_white_hud"] * 12, scores["race_gray_hud"] * 5)),
                scores,
            )

        return Detection(STATE_UNKNOWN, 0.0, scores)

    @staticmethod
    def _blurred_modal_bg(r, g, b):
        return 70 <= r <= 190 and 70 <= g <= 190 and 70 <= b <= 190
