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
app = FastAPI()
print("3 - FastAPI app created")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, tags=["Authentication"])
app.include_router(documents.router, tags=["Documents"])
app.include_router(chat.router, tags=["Chat Engine"])

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5000)