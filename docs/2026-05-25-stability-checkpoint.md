# 2026-05-25 Stability Checkpoint

## Confirmed Modes

Mode 1, EventLab skill-point farming:

- Uses in-memory window capture and screen recognition instead of blind timing.
- Recognizes the start-event menu, racing HUD, results page, restart confirmation, pause menu, and controller-disconnected modal.
- Normal loop: start event with A, hold throttle while racing, press X on results, press A on restart confirmation, then return to the event start menu.
- Screenshots are processed in memory only.

Mode 2, buy car and spend mastery points:

- Starts from the pause menu and navigates through Vehicles -> buy new/used cars -> Autoshow -> manufacturer list -> Subaru -> 1998 Impreza 22B-STI.
- Uses OCR and color/highlight checks to avoid buying the wrong car.
- After buying a 22B, returns to Vehicles -> Upgrade & Tuning -> Car Mastery.
- On the 22B mastery page, only after entering from the upgrade menu, runs the fixed sequence:

```text
A -> Right -> A -> Up -> A -> Up -> A -> Up -> A -> Left -> A
```

- The fixed sequence reaches the wheelspin skill path verified in game.
- If the final wheelspin confirmation cannot be seen, the runner stops instead of continuing a possibly wrong loop.

## Known Stable Guardrails

- The app keeps one virtual Xbox 360 controller connected while the GUI is open.
- The helper window can be set to no-activate so clicking it does not steal game focus.
- Forza focus loss still cannot be truly solved without risky hook/injection tooling, so the supported path is foreground operation plus recognition.
- The buy runner now treats pages containing "buy new car / used car / change car" as the pre-purchase vehicle tab, not as the post-purchase upgrade vehicle tab.

## Current Stop Condition

When mastery points run out, Forza shows a modal similar to:

```text
Not enough points to purchase extra perk.
```

Current behavior is acceptable for the standalone mode 2 checkpoint:

- The script stops after failing to confirm the final wheelspin skill.
- This prevents continuing the buy loop after points are exhausted.

This exhausted-points modal is the intended trigger for the next combined mode.

## Next Combined Mode Plan

Add a new mode that combines mode 2 and mode 1:

1. Buy 22B and spend mastery points until the exhausted-points modal appears.
2. Press A to close the modal and return to the mastery page.
3. Press B back to Upgrade.
4. Press B back to Vehicles.
5. Press B back to free roam.
6. Wait 1-2 seconds, then press Menu/Start to open the pause menu.
7. Navigate to Creative Hub with RB.
8. Enter EventLab, then Events, then My Favorites.
9. Start the configured EventLab skill-point farm and hand over to the existing mode 1 loop.

Implementation should keep current mode 1 and mode 2 untouched as much as possible, adding a small orchestration runner and the minimum extra detection states for:

- not-enough-skill-points modal
- Creative Hub pause tab
- EventLab menu
- EventLab Events tab
- My Favorites tab

