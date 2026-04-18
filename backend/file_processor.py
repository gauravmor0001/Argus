import os
import shutil #used for high level file operations.
from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_qdrant import QdrantVectorStore, FastEmbedSparse

def process_and_ingest_document(file_obj,filename,embedding_model,sparse_embedding_model,user_id,chunk_size=1000):
    temp_filename=f"temp_{filename}"

    try:
        with open(temp_filename,"wb") as buffer:
            shutil.copyfileobj(file_obj,buffer)
        print(f"DEBUG: processing file:{temp_filename} for User ID:{user_id}")

        if temp_filename.endswith(".pdf"):
            loader=PyPDFLoader(temp_filename)
        elif temp_filename.endswith(".docx"):
            loader=Docx2txtLoader(temp_filename)
        else:
            loader=TextLoader(temp_filename)
        
        docs=loader.load()

        text_splitter=RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=200)
        splits=text_splitter.split_documents(docs)

        for split in splits:
            split.metadata["user_id"]=user_id

        QdrantVectorStore.from_documents(
            splits,
            embedding_model,
            sparse_embedding=sparse_embedding_model, # Generates BM25 keywords for each chunk
            retrieval_mode="HYBRID",
            url="http://localhost:6333",
            collection_name="learning-rag"
        )
        return True, f"Successfully learned from {filename}!"
        
    except Exception as e:
        return False, str(e)
        
    finally:
        if os.path.exists(temp_filename):
            os.remove(temp_filename)