from fastapi import APIRouter

router = APIRouter(prefix="/api/skills", tags=["Skills"])


@router.get("/local")
async def local_skills():
    return {"skills": []}
