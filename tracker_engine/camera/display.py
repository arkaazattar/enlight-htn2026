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

        # Facts left or right of the box
        if obs.person_id:
            person = memory.get(obs.person_id)
            if person and person.facts:
                import time
                num_facts = len(person.facts)
                if num_facts > 3:
                    offset = int(time.time() / 5) % num_facts
                    facts_to_show = [person.facts[(offset + i) % num_facts] for i in range(3)]
                else:
                    facts_to_show = person.facts
                
                # Format text
                lines = [f"- {f[:45]}" for f in facts_to_show]
                
                # Calculate dimensions
                font_scale = 0.55
                thickness = 1
                line_heights = []
                max_w = 0
                for line in lines:
                    (tw, th), _ = cv2.getTextSize(line, _FONT, font_scale, thickness)
                    max_w = max(max_w, tw)
                    line_heights.append(th)
                
                pad = 8
                total_h = sum(line_heights) + (len(lines) - 1) * 10 + 2 * pad
                total_w = max_w + 2 * pad
                
                # Try left first
                rx, ry, rw, rh = x - total_w - 5, y + 10, total_w, total_h
                
                def is_obstructed(cx, cy, cw, ch):
                    if cx < 0 or cx + cw > w or cy < 0 or cy + ch > h:
                        return True
                    for o in observations:
                        if o is obs: continue
                        ox, oy, obw, obh = (int(v) for v in o.box[:4])
                        if not (cx + cw < ox or cx > ox + obw or cy + ch < oy or cy > oy + obh):
                            return True
                    return False
                
                if is_obstructed(rx, ry, rw, rh):
                    # Try right
                    rx2, ry2, rw2, rh2 = x + bw + 5, y + 10, total_w, total_h
                    if not is_obstructed(rx2, ry2, rw2, rh2):
                        rx, ry, rw, rh = rx2, ry2, rw2, rh2
                    else:
                        # Fallback to whichever has more space
                        if x > w - (x + bw):
                            rx = max(0, x - total_w - 5)
                        else:
                            rx = min(w - total_w, x + bw + 5)
                
                # Draw background
                overlay = frame.copy()
                cv2.rectangle(overlay, (int(rx), int(ry)), (int(rx + rw), int(ry + rh)), (30, 30, 30), -1)
                cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)
                
                # Draw text
                text_y = ry + pad
                for i, line in enumerate(lines):
                    cv2.putText(frame, line, (int(rx + pad), int(text_y + line_heights[i])), _FONT, font_scale, _CYAN, thickness)
                    text_y += line_heights[i] + 10

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
