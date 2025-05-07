from fastapi import APIRouter, Request, HTTPException, Response, Depends
import json
from pathlib import Path

# ---- User store ----
USERS_FILE = Path("data/users.json")
# Ensure the users file exists; initialize with your codewords
if not USERS_FILE.exists():
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(json.dumps({
        "open-sesame": {"name": "Rohit", "created_at": "2025-05-07T00:00:00"}
    }, indent=2))

USERS = json.loads(USERS_FILE.read_text())

router = APIRouter()

# ---- Auth dependency ----
def require_user(request: Request):
    codeword = request.cookies.get("rubi_sid")
    if not codeword or codeword not in USERS:
        raise HTTPException(status_code=401, detail="Invalid or missing codeword")
    return {"codeword": codeword, **USERS[codeword]}

# ---- Endpoints ----
@router.post("/auth/login")
async def login(payload: dict, response: Response):
    codeword = payload.get("codeword")
    if not codeword or codeword not in USERS:
        raise HTTPException(status_code=401, detail="Invalid codeword")
    # Set HttpOnly cookie
    response.set_cookie(key="rubi_sid", value=codeword, httponly=True, samesite="lax")
    return {"status": "ok"}

@router.get("/auth/whoami")
async def whoami(user = Depends(require_user)):
    # Returns codeword and associated metadata
    return user
