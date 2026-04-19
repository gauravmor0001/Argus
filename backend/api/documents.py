from fastapi import APIRouter, File, UploadFile, Header
from typing import Optional
from langchain_huggingface import HuggingFaceEmbeddings
from file_processor import process_and_ingest_document
from api.auth import verify_token
from langchain_qdrant import FastEmbedSparse
from database import UserDatabase
from qdrant_client import QdrantClient
from qdrant_client.http import models

router = APIRouter()
db = UserDatabase()
embedding_model = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)
sparse_embedding_model = FastEmbedSparse(
    model_name="Qdrant/bm25"
)

@router.post("/upload-doc")
async def upload_and_ingest(
    file: UploadFile=File(...),
    authorization: Optional[str]=Header(None) #this checks if authorization(metadata header in http) is present or not.if yes user is loged in.the authorization string looks like "Bearer ....."this is a JWT.
    ):
        try:
            user_id, username=verify_token(authorization)

            success,message=process_and_ingest_document(
                file_obj=file.file,
                filename=file.filename,
                embedding_model=embedding_model,
                sparse_embedding_model=sparse_embedding_model,
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
        
        # Fetch the files from our new SQL table
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
        
        # Note: In your file_processor, the file is saved as 'temp_filename.pdf' 
        # so the Langchain metadata automatically sets the source to that exact string.
        source_name = f"temp_{filename}" 
        
        client = QdrantClient(url="http://localhost:6333")
        
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