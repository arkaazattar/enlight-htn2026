from fastapi.testclient import TestClient
from backend.main import app

with TestClient(app) as client:
    # 1. Create a person
    res1 = client.post("/people", json={"name": "test person", "description": ""})
    print("CREATE PERSON:", res1.status_code, res1.text)
    if res1.status_code == 200:
        person_id = res1.json()["id"]
        # 2. Upload a dummy picture
        with open("dummy.jpg", "rb") as f:
            res2 = client.post(f"/people/{person_id}/pictures", files={"file": ("dummy.jpg", f, "image/jpeg")})
        print("UPLOAD PICTURE:", res2.status_code, res2.text)
