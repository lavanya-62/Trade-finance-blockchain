from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from datetime import datetime
from typing import List, Dict
from jose import jwt
import hashlib
import os
import secrets

# Production: Disable docs + hide test data
app = FastAPI(
    title="TradeChain Explorer", 
    docs_url=None if os.getenv("ENV") == "prod" else "/docs",
    redoc_url=None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Models
class LoginRequest(BaseModel):
    email: str
    password: str

class RegisterRequest(BaseModel):
    email: str
    password: str
    role: str
    org_name: str

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")
users_db: Dict[str, Dict] = {}
documents_db: List[Dict] = []
next_doc_id = 1

# Password hashing
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(plain: str, hashed: str) -> bool:
    return hash_password(plain) == hashed

# JWT
SECRET_KEY = secrets.token_hex(32)
ALGORITHM = "HS256"

def create_token(data: dict):
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str):
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

@app.post("/auth/register")
async def register(request: RegisterRequest):
    if request.email in users_db:
        raise HTTPException(400, "Email exists")
    
    user_id = str(secrets.token_hex(8))
    users_db[user_id] = {
        "id": user_id,
        "email": request.email,
        "password": hash_password(request.password),
        "role": request.role.lower(),
        "org_name": request.org_name
    }
    return {"message": "User created"}

@app.post("/auth/login")
async def login(request: LoginRequest):
    for user_id, user in users_db.items():
        if (user["email"] == request.email and 
            verify_password(request.password, user["password"])):
            token = create_token({"sub": user["email"], "id": user_id})
            return {"access_token": token, "token_type": "bearer"}
    raise HTTPException(401, "Invalid credentials")

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.post("/documents/")
async def upload_document(
    file: UploadFile = File(...),
    token: str = Depends(oauth2_scheme)
):
    global next_doc_id
    user = get_current_user(token)
    
    contents = await file.read()
    file_hash = hashlib.sha256(contents).hexdigest()
    
    # Check duplicate
    for doc in documents_db:
        if doc["hash"] == file_hash:
            raise HTTPException(409, "Duplicate document")
    
    doc = {
        "id": next_doc_id,
        "filename": file.filename,
        "user_id": user["id"],
        "status": "pending",
        "hash": file_hash,
        "timestamp": datetime.now().isoformat(),
        "size": len(contents)
    }
    documents_db.append(doc)
    next_doc_id += 1
    return doc

@app.get("/documents/")
async def list_documents(token: str = Depends(oauth2_scheme), skip: int = 0, limit: int = 10):
    user = get_current_user(token)
    user_docs = [d for d in documents_db if d["user_id"] == user["id"]]
    return user_docs[skip:skip+limit]

@app.post("/documents/{doc_id}/verify")
async def verify_doc(doc_id: int, token: str = Depends(oauth2_scheme)):
    user = get_current_user(token)
    if user["role"] != "importer":
        raise HTTPException(403, "Only importers can verify")
    
    for doc in documents_db:
        if doc["id"] == doc_id:
            doc["status"] = "verified"
            return {"status": "verified"}
    raise HTTPException(404, "Document not found")

@app.post("/documents/{doc_id}/approve")
async def approve_doc(doc_id: int, token: str = Depends(oauth2_scheme)):
    user = get_current_user(token)
    if user["role"] != "exporter":
        raise HTTPException(403, "Only exporters can approve")
    
    for doc in documents_db:
        if doc["id"] == doc_id:
            doc["status"] = "approved"
            return {"status": "approved"}
    raise HTTPException(404, "Document not found")

@app.post("/documents/{doc_id}/reject")
async def reject_doc(doc_id: int, token: str = Depends(oauth2_scheme)):
    user = get_current_user(token)
    if user["role"] != "exporter":
        raise HTTPException(403, "Only exporters can reject")
    
    for doc in documents_db:
        if doc["id"] == doc_id:
            doc["status"] = "rejected"
            return {"status": "rejected"}
    raise HTTPException(404, "Document not found")
