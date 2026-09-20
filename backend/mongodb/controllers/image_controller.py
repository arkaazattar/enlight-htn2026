"""MongoDB image controller — APIRouter for person images and pictures."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import Response

from backend.mongodb.handlers.people_handler import PNG_SIGNATURE, MongoError, Person
from backend.mongodb.controllers.people_controller import get_service, get_picture_repo
from backend.graph_lib.controllers.graph_controller import get_graph_db
from backend.mongodb.handlers.people_handler import person_id_to_node_id
image_router = APIRouter(prefix="/people", tags=["Images"])


@image_router.get("/{person_id}/image")
def get_person_image(person_id: str):
    """Serve the person's face image as PNG."""
    svc = get_service()
    try:
        with svc.lock:
            person = svc.repository.get(person_id)
            if not person.picture_ids:
                raise HTTPException(status_code=404, detail="No picture")
            
            pic_id = person.picture_ids[0]
            
            face_path = svc.repository.resolve_path(f"faces/{pic_id}.png")
            if face_path.exists():
                return Response(content=face_path.read_bytes(), media_type="image/png")
            img_path = svc.repository.resolve_path(f"images/{pic_id}.png")
            if img_path.exists():
                return Response(content=img_path.read_bytes(), media_type="image/png")
            
            try:
                picture_repo = get_picture_repo()
                pic = picture_repo.get(pic_id)
                pic_path = picture_repo.resolve_path(pic.path)
                return Response(content=pic_path.read_bytes(), media_type="image/png")
            except Exception:
                pass
                
            raise HTTPException(status_code=404, detail="Picture not found")
    except MongoError as e:
        raise HTTPException(status_code=404, detail=str(e))


@image_router.get("/{person_id}/pictures")
def get_pictures(person_id: str):
    """Get all picture paths linked to a person."""
    svc = get_service()
    try:
        with svc.lock:
            person = svc.repository.get(person_id)
        return {"picture_ids": person.picture_ids}
    except MongoError as e:
        raise HTTPException(status_code=404, detail=str(e))


@image_router.post("/{person_id}/pictures", response_model=Person)
async def add_picture(person_id: str, file: Annotated[UploadFile, File(...)]):
    """Upload a new picture and link it to the person."""
    svc = get_service()
    try:
        with svc.lock:
            person = svc.repository.get(person_id)
            img_bytes = await file.read()
            if not img_bytes.startswith(PNG_SIGNATURE):
                from io import BytesIO
                from PIL import Image
                try:
                    img = Image.open(BytesIO(img_bytes))
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                    out = BytesIO()
                    img.save(out, format="PNG")
                    img_bytes = out.getvalue()
                except Exception as e:
                    raise HTTPException(status_code=400, detail=f"Unsupported image format: {e}")

            picture_repo = get_picture_repo()
            picture = picture_repo.create(img_bytes)

            if not person.picture_ids:
                
                try:
                    graph = get_graph_db()
                    node = graph.get_node(person_id_to_node_id(person_id))
                    name = node.name if node and node.name else person_id
                except Exception:
                    name = person_id

                faces_dir = svc.repository.root / "faces"
                faces_dir.mkdir(parents=True, exist_ok=True)
                
                face_path = faces_dir / f"{name}.png"
                face_path.write_bytes(img_bytes)

            return svc.repository.add_picture_id(person_id, picture.id)
    except MongoError as e:
        raise HTTPException(status_code=400, detail=str(e))
