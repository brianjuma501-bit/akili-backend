import os
import base64
import requests
from datetime import datetime, date
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
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

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
PAYPAL_EMAIL = os.getenv("PAYPAL_EMAIL", "brianjuma501@gmail.com")
MPESA_NUMBER = os.getenv("MPESA_NUMBER", "0795400348")
OWNER_IDS = set(os.getenv("OWNER_IDS", "user_6g9hpkt5s,user_kpw84638a").split(","))
DARAJA_CONSUMER_KEY = os.getenv("DARAJA_CONSUMER_KEY", "")
DARAJA_CONSUMER_SECRET = os.getenv("DARAJA_CONSUMER_SECRET", "")
DARAJA_SHORTCODE = os.getenv("DARAJA_SHORTCODE", "174379")
DARAJA_PASSKEY = os.getenv("DARAJA_PASSKEY", "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919")
DARAJA_CALLBACK_URL = os.getenv("DARAJA_CALLBACK_URL", "https://akili-backend.onrender.com/mpesa-callback")

FREE_TRIAL_LIMIT = 1
DAILY_LIMIT = 20

user_data = {}
request_counts = {}
used_codes = set()


def get_user(user_id: str):
    if user_id not in user_data:
        user_data[user_id] = {
            "trial_used": 0,
            "entry_paid": False,
            "daily_count": 0,
            "last_reset": str(date.today()),
            "chats": {},
            "is_member": False
        }
    u = user_data[user_id]
    if u["last_reset"] != str(date.today()):
        u["daily_count"] = 0
        u["last_reset"] = str(date.today())
    return u


def call_gemini(system_prompt: str, messages: list) -> str:
    if not GEMINI_API_KEY:
        return "Gemini API key not configured."
    try:
        combined = system_prompt + "\n\n"
        for m in messages:
            role = "User" if m["role"] == "user" else "Akili"
            combined += f"{role}: {m['content']}\n"
        combined += "Akili:"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": combined}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1000}
        }
        response = requests.post(url, json=payload, timeout=30)
        data = response.json()
        if "candidates" in data and len(data["candidates"]) > 0:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        elif "error" in data:
            return f"AI error: {data['error'].get('message', 'Unknown')}"
        else:
            return "Could not get a response. Please try again."
    except requests.exceptions.Timeout:
        return "Request timed out. Please try again."
    except Exception as e:
        return f"Error: {str(e)}"


def get_mpesa_token():
    try:
        if not DARAJA_CONSUMER_KEY or not DARAJA_CONSUMER_SECRET:
            return None
        credentials = base64.b64encode(
            f"{DARAJA_CONSUMER_KEY}:{DARAJA_CONSUMER_SECRET}".encode()
        ).decode()
        response = requests.get(
            "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials",
            headers={"Authorization": f"Basic {credentials}"},
            timeout=10
        )
        return response.json().get("access_token")
    except Exception:
        return None


def generate_mpesa_password():
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    data = base64.b64encode(
        f"{DARAJA_SHORTCODE}{DARAJA_PASSKEY}{timestamp}".encode()
    ).decode()
    return data, timestamp


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    system: str
    messages: list[Message]
    user_id: str


class SaveChatRequest(BaseModel):
    user_id: str
    chat_id: str
    title: str
    messages: list[Message]


class DeleteChatRequest(BaseModel):
    user_id: str
    chat_id: str


class STKRequest(BaseModel):
    user_id: str
    phone_number: str
    amount: int = 130


class VerifyPaymentRequest(BaseModel):
    user_id: str
    transaction_code: str
    payment_method: str


@app.get("/")
def health_check():
    return {
        "status": "Akili backend is running",
        "gemini_key_set": bool(GEMINI_API_KEY),
        "version": "3.0"
    }


@app.get("/ping")
def ping():
    return {"pong": True}


@app.get("/payment-info")
def payment_info():
    return {
        "paypal_email": PAYPAL_EMAIL,
        "paypal_link_entry": "https://paypal.me/brianjuma501/1",
        "paypal_link_subscription": "https://paypal.me/brianjuma501/7.25",
        "mpesa_number": MPESA_NUMBER,
        "entry_price_kes": 130,
        "entry_price_usd": 1,
        "subscription_price_usd": 7.25,
        "trial_messages": FREE_TRIAL_LIMIT,
        "daily_limit": DAILY_LIMIT
    }


@app.get("/user-status/{user_id}")
def user_status(user_id: str):
    if user_id in OWNER_IDS:
        return {
            "is_owner": True,
            "can_chat": True,
            "needs_entry": False,
            "needs_subscription": False,
            "trial_used": 0,
            "daily_count": 0,
            "entry_paid": True,
            "is_member": True,
            "daily_remaining": 999
        }
    u = get_user(user_id)
    in_trial = u["trial_used"] < FREE_TRIAL_LIMIT
    needs_entry = not in_trial and not u["entry_paid"]
    needs_subscription = u["entry_paid"] and u["is_member"] and u["daily_count"] >= DAILY_LIMIT
    can_chat = in_trial or (u["entry_paid"] and u["daily_count"] < DAILY_LIMIT)
    return {
        "is_owner": False,
        "can_chat": can_chat,
        "needs_entry": needs_entry,
        "needs_subscription": needs_subscription,
        "trial_used": u["trial_used"],
        "daily_count": u["daily_count"],
        "entry_paid": u["entry_paid"],
        "is_member": u["is_member"],
        "trial_remaining": max(0, FREE_TRIAL_LIMIT - u["trial_used"]),
        "daily_remaining": max(0, DAILY_LIMIT - u["daily_count"]) if u["entry_paid"] else 0
    }


@app.post("/stk-push")
def stk_push(req: STKRequest):
    token = get_mpesa_token()
    if not token:
        return {"success": False, "message": "M-Pesa auto-prompt unavailable. Please send manually."}
    try:
        password, timestamp = generate_mpesa_password()
        phone = req.phone_number.strip().replace(" ", "")
        if phone.startswith("0"):
            phone = "254" + phone[1:]
        elif phone.startswith("+"):
            phone = phone[1:]
        payload = {
            "BusinessShortCode": DARAJA_SHORTCODE,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": req.amount,
            "PartyA": phone,
            "PartyB": DARAJA_SHORTCODE,
            "PhoneNumber": phone,
            "CallBackURL": DARAJA_CALLBACK_URL,
            "AccountReference": f"AKILI{req.user_id[:6].upper()}",
            "TransactionDesc": "Akili AI"
        }
        response = requests.post(
            "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=15
        )
        result = response.json()
        if result.get("ResponseCode") == "0":
            return {"success": True, "message": "M-Pesa prompt sent! Enter your PIN."}
        else:
            return {"success": False, "message": "Could not send prompt. Please send manually."}
    except Exception:
        return {"success": False, "message": "M-Pesa error. Please send manually."}


@app.post("/mpesa-callback")
async def mpesa_callback(request: Request):
    try:
        body = await request.json()
        result = body.get("Body", {}).get("stkCallback", {})
        if result.get("ResultCode") == 0:
            metadata = result.get("CallbackMetadata", {}).get("Item", [])
            account_ref = next(
                (i["Value"] for i in metadata if i["Name"] == "AccountReference"), None
            )
            if account_ref and account_ref.startswith("AKILI"):
                user_prefix = account_ref.replace("AKILI", "").lower()
                for uid in user_data:
                    if uid.startswith(user_prefix):
                        user_data[uid]["entry_paid"] = True
                        user_data[uid]["is_member"] = True
                        user_data[uid]["daily_count"] = 0
                        break
    except Exception:
        pass
    return {"ResultCode": 0, "ResultDesc": "Accepted"}


@app.post("/verify-payment")
def verify_payment(req: VerifyPaymentRequest):
    code = req.transaction_code.strip().upper()
    if not code or len(code) < 8:
        return {"success": False, "message": "Please enter a valid transaction code."}
    if code in used_codes:
        return {"success": False, "message": "This code has already been used."}
    used_codes.add(code)
    u = get_user(req.user_id)
    if req.payment_method == "subscription":
        u["daily_count"] = 0
        return {"success": True, "message": "Subscribed! Keep chatting!"}
    else:
        u["entry_paid"] = True
        u["is_member"] = True
        u["daily_count"] = 0
        return {"success": True, "message": "Welcome to Akili! You now have 20 messages per day."}


@app.post("/chat")
def chat(request: ChatRequest):
    if request.user_id not in OWNER_IDS:
        uid = request.user_id
        if uid not in request_counts:
            request_counts[uid] = {"count": 0, "window": datetime.now().timestamp()}
        rc = request_counts[uid]
        now = datetime.now().timestamp()
        if now - rc["window"] < 60:
            if rc["count"] > 30:
                return {"error": "RATE_LIMIT", "message": "Too many requests. Please wait."}
            rc["count"] += 1
        else:
            rc["count"] = 1
            rc["window"] = now
        u = get_user(request.user_id)
        if u["trial_used"] < FREE_TRIAL_LIMIT:
            u["trial_used"] += 1
        elif not u["entry_paid"]:
            return {"error": "NEEDS_ENTRY", "message": "Pay KSh 130 to become a member."}
        elif u["daily_count"] < DAILY_LIMIT:
            u["daily_count"] += 1
        else:
            return {"error": "NEEDS_SUBSCRIPTION", "message": "Daily limit reached. Pay to continue."}
    reply = call_gemini(
        request.system,
        [{"role": m.role, "content": m.content} for m in request.messages]
    )
    return {"reply": reply}


@app.post("/save-chat")
def save_chat(req: SaveChatRequest):
    u = get_user(req.user_id)
    u["chats"][req.chat_id] = {
        "title": req.title,
        "messages": [{"role": m.role, "content": m.content} for m in req.messages],
        "saved_at": str(datetime.now())
    }
    return {"success": True}


@app.get("/get-chats/{user_id}")
def get_chats(user_id: str):
    u = get_user(user_id)
    return {"chats": u["chats"]}


@app.post("/delete-chat")
def delete_chat(req: DeleteChatRequest):
    u = get_user(req.user_id)
    if req.chat_id in u["chats"]:
        del u["chats"][req.chat_id]
    return {"success": True}
