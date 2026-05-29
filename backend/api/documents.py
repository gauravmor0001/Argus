print("documents.py loading")
from fastapi import APIRouter, File, UploadFile, Header
from typing import Optional
from file_processor import process_and_ingest_document
from api.auth import verify_token
from database import UserDatabase
from qdrant_client import QdrantClient
from qdrant_client.http import models
import os

router = APIRouter()
db = UserDatabase()

# --- LAZY MODEL SINGLETONS ---
# Models are NOT loaded at import time.
# They are loaded the first time /upload-doc is actually called.
# This allows uvicorn to bind the port instantly, fixing the Render deployment issue.

_embedding_model = None
_sparse_model = None

def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        print("[Models] Loading remote HF embedding model...")
        from langchain_huggingface import HuggingFaceEndpointEmbeddings
        _embedding_model = HuggingFaceEndpointEmbeddings(
            model="sentence-transformers/all-MiniLM-L6-v2",
            huggingfacehub_api_token=os.getenv("HUGGINGFACEHUB_API_TOKEN")
        )
        print("[Models] Remote embedding model ready.")
    return _embedding_model

def get_sparse_model():
    global _sparse_model
    if _sparse_model is None:
        print("[Models] Loading sparse embedding model (documents)...")
        from langchain_qdrant import FastEmbedSparse
        _sparse_model = FastEmbedSparse(model_name="Qdrant/bm25")
        print("[Models] Sparse model ready.")
    return _sparse_model

# -----------------------------

@router.post("/upload-doc")
async def upload_and_ingest(
    file: UploadFile=File(...),  # here the "file:" is the variable name the frontend is sending(should match the fronted)-> formData.append("file", selectedFile);
    authorization: Optional[str]=Header(None)  # this checks if authorization(metadata header in http) is present or not.if yes user is loged in.the authorization string looks like "Bearer ....."this is a JWT.
    ):
        try:
            user_id, username = verify_token(authorization)

            # Models are fetched lazily here — loaded only on first actual upload call
            success, message = process_and_ingest_document(
                file_obj=file.file,
                filename=file.filename,
                embedding_model=get_embedding_model(),
                sparse_embedding_model=get_sparse_model(),
                user_id=user_id
            )
            if success:
                db.add_file(user_id, file.filename)
                return {"status": "success", "message": message}
            else:
                return {"status": "error", "message": message}

        except Exception as e:
            return {"status": "error", "message": str(e)}
        

@router.get("/files")
async def get_user_files(authorization: Optional[str] = Header(None)):
    """Fetches the list of files uploaded by the logged-in user."""
    try:
        user_id, username = verify_token(authorization)
        
        files = db.get_files(user_id)
        
        return {"status": "success", "files": files}
        
    except Exception as e:
        return {"status": "error", "message": str(e)}
    
@router.delete("/files/{file_id}")
async def delete_user_file(file_id: str, authorization: Optional[str] = Header(None)):
    """Deletes a file record from SQL and scrubs all its vector chunks from Qdrant."""
    try:
        user_id, username = verify_token(authorization)
        
        # 1. Delete from SQL and get the original filename
        filename = db.delete_file_record(file_id, user_id)
        
        if not filename:
            return {"status": "error", "message": "File not found or unauthorized"}
        
        source_name = f"temp_{filename}" 
        
        client = QdrantClient(
            url=os.getenv("qdrant_url"),        
            api_key=os.getenv("qdrant_cloud_key") 
        )
        
        client.delete(
            collection_name="learning-rag",
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="metadata.user_id", 
                            match=models.MatchValue(value=user_id)
                        ),
                        models.FieldCondition(
                            key="metadata.source", 
                            match=models.MatchValue(value=source_name)
                        )
                    ]
                )
            )
        )
        
        return {"status": "success", "message": f"{filename} deleted successfully"}
        
    except Exception as e:
        print(f"DEBUG: Delete File Error: {e}")
        return {"status": "error", "message": str(e)}