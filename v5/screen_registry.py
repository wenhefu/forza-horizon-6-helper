"""Declarative Forza UI knowledge model + generic route planner (V5 skeleton).

This FORMALIZES the model that is today implicit across `v3/ui_tree.py` (the
screen tree: parent/child, tabs, options) and `v4/decision.py` (the de-facto
"screen -> button -> next screen" transition rules). It does NOT duplicate the
48-screen tree -- it is built by iterating `v3.ui_tree` and adds:

- explicit `Transition` edges (child / synthesized parent / synthesized tab),
- per-screen `RecoveryAction`s (new knowledge, e.g. the "找不到赛事" network glitch),
- a generic `plan_route()` (BFS) + `next_button()` so the program can navigate
  "from any screen toward a goal screen" instead of via hand-written routes.

Phase-1 scope: the data model + the navigator + a few enriched screens + the
empty-events recovery. It does NOT yet migrate the full `decide_*` logic (that is
phase 2 -- the `trigger` field on child edges is where target-confirm guards will
attach) and tab routing uses a representative `RB` step (phase 2 computes the
exact LB/RB x N from the active tab via `_tab_button`).

Recognition stays in `v3/hybrid.py`; this module only CONSUMES a recognition
result (anything exposing `.screen`, `.selected_item`, `.ocr_regions[*].text`).
Imports are light on purpose (only `v3.ui_tree` + `v4.decision.normalize_button`)
so the navigator is pure-logic and unit-testable without a game/frames.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from v3.ui_tree import SCREEN_TO_NODE, UI_NODES
from v4.decision import normalize_button


# --- data model -----------------------------------------------------------

@dataclass(frozen=True)
class Transition:
    """A directed edge between two SCREENS.

    kind:
      "child"  -- press a button to enter a sub-page (from ui_tree children)
      "parent" -- press B to go up one level (synthesized from ui_tree parent)
      "tab"    -- switch top tabs (LB/RB) to a sibling screen (representative button)
    """

    button: str
    target: str
    verify: str = ""
    trigger: str = ""
    kind: str = "child"

    @property
    def norm_button(self) -> str:
        return normalize_button(self.button)

    @property
    def actionable(self) -> bool:
        # State-only edges (e.g. race_hud --""--> race_result on finish) carry no
        # pressable button and must not be used as navigation steps.
        return bool(self.norm_button)


@dataclass(frozen=True)
class RecoveryAction:
    """A recoverable sub-state of a screen, matched from OCR text.

    Distinct from normal navigation: it heals an abnormal-but-recognizable state
    (e.g. an empty event list from a network glitch) before routing resumes.
    """

    name: str
    button: str
    reason: str
    verify: str
    detect_tokens: tuple[str, ...] = ()
    wait_then_retry: bool = False
    max_attempts: int = 3
    confidence: float = 0.0

    def matches(self, understanding) -> bool:
        if not self.detect_tokens:
            return False
        hay = _normalize_text(_gather_text(understanding))
        return all(_normalize_text(tok) in hay for tok in self.detect_tokens)


@dataclass(frozen=True)
class ScreenSpec:
    screen: str
    node_id: str
    detect: str = ""
    title: str = ""
    tab_scope: str = ""
    tabs: tuple[str, ...] = ()
    options: tuple[str, ...] = ()
    transitions: tuple[Transition, ...] = ()
    recovery: tuple[RecoveryAction, ...] = ()
    notes: str = ""

    @property
    def ui_node(self):
        """Live reference into v3.ui_tree (source of truth for structure)."""
        return UI_NODES.get(self.node_id)


@dataclass(frozen=True)
class ScreenRegistry:
    specs: dict[str, ScreenSpec] = field(default_factory=dict)

    def get(self, screen: str) -> ScreenSpec | None:
        return self.specs.get(screen)

    def neighbors(self, screen: str) -> list[Transition]:
        spec = self.specs.get(screen)
        return list(spec.transitions) if spec else []


@dataclass(frozen=True)
class NextAction:
    button: str
    reason: str
    verify: str = ""
    name: str = ""
    recovery: bool = False
    confidence: float = 0.0

    @property
    def norm_button(self) -> str:
        return normalize_button(self.button)


class NoRouteError(Exception):
    def __init__(self, start: str, goal: str):
        super().__init__(f"no button route from {start!r} to {goal!r}")
        self.start = start
        self.goal = goal


# --- text helpers (mirror v3.ui_names / v4.decision._combined_text) ---------

def _normalize_text(text: str) -> str:
    # Uppercase + drop all whitespace; keeps CJK so "找不到赛事" matches literally.
    return "".join(str(text or "").upper().split())


def _gather_text(understanding) -> str:
    parts = [str(getattr(understanding, "selected_item", "") or "")]
    for region in getattr(understanding, "ocr_regions", None) or []:
        parts.append(str(getattr(region, "text", "") or ""))
    return " ".join(parts)


# --- new knowledge attached during build -----------------------------------

# The "找不到赛事 / empty events" case is NOT a distinct screen: it is the
# eventlab_events screen with that OCR token present, usually from a network
# hiccup. Model it as a recovery sub-state (the user-reported minor bug).
RECOVERY_BY_SCREEN: dict[str, tuple[RecoveryAction, ...]] = {
    "eventlab_events": (
        RecoveryAction(
            name="eventlab_empty_events_network_glitch",
            button="",  # phase-1: wait then re-detect; escalate to RB after N empties
            reason="赛事列表显示“找不到赛事”，通常是网络抖动/分页未加载，不是真的没有赛事。",
            verify="等待 1-2 秒重新识别；赛事卡片出现则恢复正常路由；连续多次仍为空再用 RB 切分页强制刷新。",
            detect_tokens=("找不到赛事",),
            wait_then_retry=True,
            max_attempts=3,
            confidence=0.80,
        ),
    ),
}

# Short note on how the hybrid recognizer decides each example label (the
# registry references detection, it never reimplements it).
DETECT_NOTES: dict[str, str] = {
    "eventlab_events": "v3 fuses to eventlab_events (V2 + EVENTLAB_TABS); empty list still classifies here with OCR token 找不到赛事.",
    "vehicle_buy_grid": "v3 YOLO/V2 + OCR (购买车辆/制造商) -> vehicle_buy_grid, distinct from the look-alike eventlab_my_cars.",
    "race_menu": "v3 race_menu (or V1 smart PRESTART); focus text 开始赛事 confirms the start tile.",
    "free_roam_hud": "v3 driving-HUD guard -> free_roam_hud (map + no lap/timer overlay).",
}

# Phase-2 migration guide: how decision.py rules map onto registry edges/recovery.
FORMALIZATION_NOTES: dict[str, str] = {
    "open_pause_from_world": "child edge free_roam_hud --Menu--> pause_story (first BFS step from the world)",
    "move_pause_tab_to_creative_hub": "tab edge pause_* --RB--> pause_creative_hub",
    "enter_eventlab_events": "child edge pause_creative_hub --A--> eventlab_home --A--> eventlab_events",
    "back_out_from_buy_flow / leave_post_race_next": "synthesized parent edges (B -> parent screen)",
    "arrived_race_menu / arrived_race_hud (terminal)": "next_button returns name='arrived' when screen == goal",
    "select_target_event / buy_select_22b (guarded A)": "child edge + Transition.trigger predicate (phase 2)",
    "eventlab empty / 找不到赛事": "RecoveryAction on eventlab_events",
}


# --- registry construction (built from v3.ui_tree, not duplicated) ----------

def _node_target_screen(node_id: str) -> str:
    """Map a ChildRoute target (a node id) to its SCREEN label."""
    node = UI_NODES.get(node_id)
    return node.screen if node is not None else node_id


def build_registry() -> ScreenRegistry:
    specs: dict[str, ScreenSpec] = {}

    # group screens by tab_scope so we can synthesize LB/RB tab edges between
    # sibling tabs (pause tabs, eventlab tabs, ...). Keyed by the tab_scope string.
    tab_groups: dict[str, list[str]] = {}
    for screen, node_id in SCREEN_TO_NODE.items():
        node = UI_NODES.get(node_id)
        if node is None or not node.tab_scope:
            continue
        tab_groups.setdefault(node.tab_scope, []).append(screen)

    for screen, node_id in SCREEN_TO_NODE.items():
        node = UI_NODES.get(node_id)
        if node is None:
            continue
        transitions: list[Transition] = []
        # 1) child edges (enter sub-pages)
        for child in node.children:
            transitions.append(
                Transition(
                    button=child.button,
                    target=_node_target_screen(child.target),
                    verify=child.verify,
                    trigger=child.trigger,
                    kind="child",
                )
            )
        # 2) synthesized parent edge (B = up one level)
        if node.parent:
            parent_node = UI_NODES.get(node.parent)
            if parent_node is not None and parent_node.screen != screen:
                transitions.append(
                    Transition(button="B", target=parent_node.screen, verify="返回上一层", kind="parent")
                )
        # 3) synthesized tab edges (LB/RB to sibling tabs; representative RB)
        if node.tab_scope:
            for sibling in tab_groups.get(node.tab_scope, ()):
                if sibling != screen:
                    transitions.append(
                        Transition(button="RB", target=sibling, verify="切到该顶部分页", kind="tab")
                    )
        specs[screen] = ScreenSpec(
            screen=screen,
            node_id=node_id,
            detect=DETECT_NOTES.get(screen, f"see v3.hybrid._fuse_screen + SCREEN_TO_NODE[{screen!r}]"),
            title=node.title,
            tab_scope=node.tab_scope,
            tabs=node.tabs,
            options=node.options,
            transitions=tuple(transitions),
            recovery=RECOVERY_BY_SCREEN.get(screen, ()),
            notes=node.notes,
        )
    return ScreenRegistry(specs)


REGISTRY = build_registry()


# --- generic navigator ------------------------------------------------------

def _reconstruct(came_from: dict, goal: str) -> list[str]:
    buttons: list[str] = []
    node = goal
    while came_from.get(node) is not None:
        prev, button = came_from[node]
        buttons.append(button)
        node = prev
    buttons.reverse()
    return buttons


def plan_route(start: str, goal: str, registry: ScreenRegistry | None = None) -> list[str]:
    """BFS over actionable child/parent/tab edges -> ordered RAW button strings.

    Returns [] if already at goal; raises NoRouteError if unreachable. Callers
    normalize buttons at press time (slash-pairs like "Back/View" are returned
    as authored). State-only edges (empty button) are skipped.
    """
    registry = registry or REGISTRY
    if start == goal:
        return []
    if start not in registry.specs:
        raise NoRouteError(start, goal)
    came_from: dict[str, tuple[str, str] | None] = {start: None}
    queue = deque([start])
    while queue:
        screen = queue.popleft()
        for transition in registry.neighbors(screen):
            if not transition.actionable:
                continue
            nxt = transition.target
            if nxt not in registry.specs or nxt in came_from:
                continue
            came_from[nxt] = (screen, transition.button)
            if nxt == goal:
                return _reconstruct(came_from, goal)
            queue.append(nxt)
    raise NoRouteError(start, goal)


def next_button(understanding, goal: str, registry: ScreenRegistry | None = None) -> NextAction:
    """One navigation decision from a recognition result toward `goal`.

    Order: recovery (heal abnormal states) -> arrived -> route step -> wait.
    This is the generic analog of one `decide_*` call.
    """
    registry = registry or REGISTRY
    screen = str(getattr(understanding, "screen", "") or "")
    if screen == goal:
        return NextAction("", "已在目标界面。", name="arrived")
    spec = registry.get(screen)
    if spec is None:
        return NextAction("", f"未知界面 {screen!r}；等待重新识别，不盲按。", name="wait_unknown")
    for rec in spec.recovery:
        if rec.matches(understanding):
            return NextAction(rec.button, rec.reason, rec.verify, name=f"recovery:{rec.name}",
                              recovery=True, confidence=rec.confidence)
    try:
        route = plan_route(screen, goal, registry)
    except NoRouteError:
        return NextAction("", f"从 {screen!r} 找不到通往 {goal!r} 的路线；等待。", name="wait_no_route")
    if route:
        return NextAction(route[0], f"路线 {screen}→{goal} 第一步：{route[0]}。",
                          verify=f"按后应朝 {goal} 前进一层。", name="route_step")
    return NextAction("", "已在目标界面。", name="arrived")
