from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ..routers.chat import router as chat_router
from ..routers.skills import router as skills_router
from ..routers.browser import router as browser_router
from ..routers.settings import router as settings_router

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
app.include_router(skills_router)
app.include_router(browser_router)
app.include_router(settings_router)