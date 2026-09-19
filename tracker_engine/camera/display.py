"""OpenCV HUD drawing.

Single responsibility: draw boxes, labels, and status onto a frame.
Reads display_dirty from Memory to know when to refresh a label.
"""

from __future__ import annotations

import cv2
import numpy as np

from ..memory import Memory


_FONT = cv2.FONT_HERSHEY_SIMPLEX
_GREEN = (0, 220, 0)
_RED = (0, 0, 230)
_CYAN = (255, 220, 0)
_WHITE = (255, 255, 255)


def draw(
    frame: np.ndarray,
    observations: list,
    memory: Memory,
    status: str = "",
    *,
    fps: float | None = None,
    mic_on: bool = True,
) -> None:
    """Draw face boxes, identity labels, and status bar onto frame in-place.

    When a TrackedPerson has display_dirty=True, we re-read their current
    name/facts from Memory and mark them clean — so the label flips on the
    very next frame after a name assignment.
    """
    h, w = frame.shape[:2]

    for obs in observations:
        x, y, bw, bh = (int(v) for v in obs.box[:4])

        if obs.person_id:
            person = memory.get(obs.person_id)
            if person and person.display_dirty:
                memory.mark_clean(obs.person_id)
            label = memory.label(obs.person_id)
            color = _GREEN
        else:
            label = "Unknown"
            color = _RED

        # Bounding box
        cv2.rectangle(frame, (x, y), (x + bw, y + bh), color, 2)

        # Name label above the box
        (lw, lh), _ = cv2.getTextSize(label, _FONT, 0.55, 2)
        label_y = max(y - 8, lh + 4)
        cv2.rectangle(frame, (x, label_y - lh - 4), (x + lw + 4, label_y + 2), color, -1)
        cv2.putText(frame, label, (x + 2, label_y), _FONT, 0.55, _WHITE, 2)

        # Facts below the box (first 2 only)
        if obs.person_id:
            person = memory.get(obs.person_id)
            if person and person.facts:
                for i, fact in enumerate(person.facts[:2]):
                    fy = y + bh + 18 + i * 18
                    if fy < h - 4:
                        cv2.putText(frame, f"· {fact[:60]}", (x, fy), _FONT, 0.40, _CYAN, 1)

    # Status bar at bottom
    if status:
        cv2.putText(frame, status[:100], (10, h - 12), _FONT, 0.45, _CYAN, 1)

    # FPS counter top-right
    if fps is not None:
        fps_text = f"{fps:.0f} fps"
        (fw, _), _ = cv2.getTextSize(fps_text, _FONT, 0.45, 1)
        cv2.putText(frame, fps_text, (w - fw - 8, 20), _FONT, 0.45, _WHITE, 1)

    # Top-left HUD bar: q: quit and MIC indicator
    cv2.putText(frame, "q: quit", (10, 20), _FONT, 0.45, _WHITE, 1)

    # Mic status indicator
    mic_color = _GREEN if mic_on else _RED
    mic_text = "MIC: ON" if mic_on else "MIC: OFF"
    cv2.circle(frame, (85, 15), 5, mic_color, -1)
    cv2.putText(frame, mic_text, (95, 20), _FONT, 0.45, mic_color, 1)
