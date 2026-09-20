"""MongoDB notes controller — APIRouter for global timeline notes."""
from __future__ import annotations

import os
import time
import datetime
from pathlib import Path
from fastapi import APIRouter

from backend.mongodb.controllers.people_controller import get_service

notes_router = APIRouter(prefix="/notes", tags=["Notes"])

@notes_router.get("")
def get_all_notes():
    """Get all notes across all people for the timeline."""
    svc = get_service()
    notes_list = []
    
    with svc.lock:
        people = svc.repository.list_people()
        for p in people:
            for note_path in p.note_paths:
                full_path = svc.repository.resolve_path(note_path)
                content = full_path.read_text(encoding="utf-8") if full_path.is_file() else None
                missing = not full_path.is_file()
                
                if full_path.is_file():
                    mod_time = os.path.getmtime(full_path)
                else:
                    mod_time = time.time()
                    
                dt_str = datetime.datetime.fromtimestamp(mod_time, tz=datetime.timezone.utc).isoformat()
                note_id = Path(note_path).stem.split("_", 1)[-1] if "_" in Path(note_path).stem else Path(note_path).stem
                
                from backend.mongodb.controllers.people_controller import _format_person
                p_info = _format_person(p)
                
                notes_list.append({
                    "id": note_id,
                    "path": note_path,
                    "content": content,
                    "missing": missing,
                    "modified_at": dt_str,
                    "person_id": p.id,
                    "person_label": p_info["label"]
                })
                
    # Sort notes by modified_at descending
    notes_list.sort(key=lambda x: x["modified_at"], reverse=True)
    return {"notes": notes_list}
