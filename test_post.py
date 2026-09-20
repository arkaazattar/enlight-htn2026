from fastapi.testclient import TestClient
from backend.main import app

with TestClient(app) as client:
    response = client.post("/posts", json={
        "person_ids": [],
        "text_content": "test note",
        "picture_id": None
    })
    print("STATUS:", response.status_code)
    print("BODY:", response.text)
