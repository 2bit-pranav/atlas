from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ..routers.chat import router as chat_router

app = FastAPI(title="Atlas API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "atlas says hi"}

app.include_router(chat_router)