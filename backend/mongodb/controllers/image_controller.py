"""MongoDB image controller — APIRouter for person images and pictures."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import Response

from backend.mongodb.handlers.people_handler import PNG_SIGNATURE, MongoError, Person
from backend.mongodb.controllers.people_controller import get_service, get_picture_repo

image_router = APIRouter(prefix="/people", tags=["Images"])


@image_router.get("/{person_id}/image")
def get_person_image(person_id: str):
    """Serve the person's face image as PNG."""
    svc = get_service()
    try:
        with svc.lock:
            png = svc.repository.image_bytes(person_id)
    except MongoError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return Response(content=png, media_type="image/png")


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
                import cv2
                import numpy as np
                decoded = cv2.imdecode(np.frombuffer(img_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
                if decoded is not None:
                    _, png_buf = cv2.imencode(".png", decoded)
                    img_bytes = png_buf.tobytes()
                else:
                    raise HTTPException(status_code=400, detail="Unsupported image format")

            picture_repo = get_picture_repo()
            picture = picture_repo.create(img_bytes)
            return svc.repository.add_picture_id(person_id, picture.id)
    except MongoError as e:
        raise HTTPException(status_code=400, detail=str(e))
