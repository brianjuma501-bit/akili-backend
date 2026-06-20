import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    system: str
    messages: list[Message]


@app.get("/")
def health_check():
    return {"status": "Akili backend is running"}


@app.post("/chat")
def chat(request: ChatRequest):
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            system=request.system,
            messages=[{"role": m.role, "content": m.content} for m in request.messages],
        )
        reply_text = "".join(
            block.text for block in response.content if hasattr(block, "text")
        )
        return {"reply": reply_text}
    except Exception as e:
        return {"error": str(e)}