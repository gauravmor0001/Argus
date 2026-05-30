print("1 - server.py started")
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
print("before auth")
from api import auth
print("before documents")
from api import documents
print("before chat")
from api import chat
print("all imports done")
print("2 - imports complete")

from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models
import os

def setup_qdrant_indexes():
    """
    Creates payload indexes on the learning-rag collection so that
    filtered searches and deletes by metadata.user_id work correctly.
    This is idempotent — safe to run every startup even if indexes exist.
    """
    try:
        client = QdrantClient(
            url=os.getenv("qdrant_url"),
            api_key=os.getenv("qdrant_cloud_key")
        )
        
        fields_to_index = [
            "metadata.user_id",   # used in search filter + delete
            "metadata.filename",  # used in search filter (target_file)
            "metadata.source",    # used in delete filter
        ]
        
        for field in fields_to_index:
            try:
                client.create_payload_index(
                    collection_name="learning-rag",
                    field_name=field,
                    field_schema=qdrant_models.PayloadSchemaType.KEYWORD
                )
                print(f"[Qdrant] Index created: {field}")
            except Exception as e:
                # "already exists" errors are fine — just skip them
                print(f"[Qdrant] Index for '{field}' skipped: {e}")
                
    except Exception as e:
        print(f"[Qdrant] Setup failed: {e}")


app = FastAPI()
print("3 - FastAPI app created")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
setup_qdrant_indexes()
app.include_router(auth.router, tags=["Authentication"])
app.include_router(documents.router, tags=["Documents"])
app.include_router(chat.router, tags=["Chat Engine"])

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5000)



