"""MongoDB posts controller — APIRouter for global timeline posts."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel

from backend.mongodb.controllers.people_controller import get_post_repo, get_note_repo, get_picture_repo, get_service, _format_person
from backend.mongodb.handlers.people_handler import MongoError

posts_router = APIRouter(prefix="/posts", tags=["Posts"])

class PostCreateRequest(BaseModel):
    person_ids: list[str] = []
    text_content: str | None = None
    picture_id: str | None = None

@posts_router.get("")
def get_all_posts():
    """Get all posts for the timeline."""
    post_repo = get_post_repo()
    note_repo = get_note_repo()
    picture_repo = get_picture_repo()
    person_service = get_service()

    posts_list = []
    
    try:
        posts = post_repo.list_posts()
        for post in posts:
            # Fetch Note content
            note_content = None
            if post.note_id:
                try:
                    note = note_repo.get(post.note_id)
                    note_path = note_repo.resolve_path(note.path)
                    note_content = note_path.read_text(encoding="utf-8") if note_path.is_file() else None
                except MongoError:
                    pass

            # Fetch Picture URL
            picture_url = None
            if post.picture_id:
                picture_url = f"/posts/pictures/{post.picture_id}"

            # Fetch People info
            tagged_people = []
            for pid in post.person_ids:
                try:
                    p = person_service.repository.get(pid)
                    p_info = _format_person(p)
                    tagged_people.append({
                        "id": p.id,
                        "label": p_info["label"],
                        "image_url": p_info["image_url"]
                    })
                except MongoError:
                    pass

            posts_list.append({
                "id": post.id,
                "created_at": post.created_at.isoformat(),
                "note_content": note_content,
                "picture_url": picture_url,
                "tagged_people": tagged_people
            })

    except MongoError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"posts": posts_list}

@posts_router.post("")
def create_post(request: PostCreateRequest):
    """Create a new post with text, picture, and people."""
    post_repo = get_post_repo()
    note_repo = get_note_repo()
    picture_repo = get_picture_repo()
    person_service = get_service()

    if not request.text_content and not request.picture_id:
        raise HTTPException(status_code=400, detail="Post must have at least one note or picture.")

    try:
        note_id = None
        if request.text_content:
            note = note_repo.create(request.text_content)
            note_id = note.id

        if request.picture_id:
            picture_repo.get(request.picture_id) # verify it exists

        post = post_repo.create(
            person_ids=request.person_ids,
            note_id=note_id,
            picture_id=request.picture_id
        )

        # Update each tagged person with the post_id
        for pid in request.person_ids:
            person_service.repository.add_post_id(pid, post.id)

        return {"id": post.id, "status": "ok"}
    except MongoError as e:
        raise HTTPException(status_code=400, detail=str(e))

@posts_router.post("/pictures")
def upload_picture(file: UploadFile = File(...)):
    """Upload a picture for a post."""
    picture_repo = get_picture_repo()
    try:
        data = file.file.read()
        picture = picture_repo.create(data)
        return {"picture_id": picture.id}
    except MongoError as e:
        raise HTTPException(status_code=400, detail=str(e))

@posts_router.get("/pictures/{picture_id}")
def get_picture(picture_id: str):
    """Serve the picture as PNG."""
    picture_repo = get_picture_repo()
    try:
        picture = picture_repo.get(picture_id)
        png = picture_repo.resolve_path(picture.path).read_bytes()
        return Response(content=png, media_type="image/png")
    except MongoError as e:
        raise HTTPException(status_code=404, detail=str(e))
