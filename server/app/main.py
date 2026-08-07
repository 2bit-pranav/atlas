from fastapi import FastAPI

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "atlas says hi"}

@app.get("/chats")
async def get_chats():
    return "list of chats"

@app.post("/chats")
async def post_chats():
    return "a new chat was created"

@app.get("/chats/{id}")
async def get_chats_with_id(id: str):
    return f"chat #{id}"

@app.delete("/chats/{id}")
async def delete_chat_with_id(id: str):
    return f"chat #{id} was deleted"

@app.patch("/chats/{id}")
async def patch_chat_with_id(id: str):
    return f"chat #{id} was updated"