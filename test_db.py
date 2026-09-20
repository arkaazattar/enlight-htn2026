from backend.mongodb.handlers.people_handler import PersonRepository, MongoError
from backend.mongodb.handlers.post_handler import PictureRepository
import asyncio
from datetime import datetime

people_repo = PersonRepository.from_environment()
pic_repo = PictureRepository.from_environment()

print("People count:", len(people_repo.list_people()))
for p in people_repo.list_people():
    print(f"Person: {p.id}, picture_ids: {p.picture_ids}")

