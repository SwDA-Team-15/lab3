import os
import json
import asyncio
import smtplib
from email.message import EmailMessage
import requests
import aio_pika
from dotenv import load_dotenv

load_dotenv()

# Configuration
API_URL = os.getenv("MZINGA_API_URL")
ADMIN_EMAIL = os.getenv("MZINGA_ADMIN_EMAIL")
ADMIN_PASSWORD = os.getenv("MZINGA_ADMIN_PASSWORD")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")
EXCHANGE_NAME = os.getenv("EXCHANGE_NAME", "mzinga_events_durable")
QUEUE_NAME = os.getenv("QUEUE_NAME", "communications-email-worker")
ROUTING_KEY = os.getenv("ROUTING_KEY", "HOOKSURL_COMMUNICATIONS_AFTERCHANGE")
SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", 1025))
EMAIL_FROM = os.getenv("EMAIL_FROM", "worker@mzinga.io")

token = None

def authenticate():
    global token
    res = requests.post(f"{API_URL}/users/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    res.raise_for_status()
    token = res.json().get("token")

def api_request(method, endpoint, **kwargs):
    global token
    if not token: authenticate()
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    url = f"{API_URL}{endpoint}"
    
    # Run request in a thread to prevent blocking the async event loop
    res = requests.request(method, url, headers=headers, **kwargs)
    
    if res.status_code == 401:
        authenticate()
        headers["Authorization"] = f"Bearer {token}"
        res = requests.request(method, url, headers=headers, **kwargs)
        
    res.raise_for_status()
    return res

def serialize_slate_to_text(body):
    text = ""
    if not body: return text
    for node in body:
        if 'children' in node:
            for child in node['children']:
                text += child.get('text', '') + " "
        text += "\n"
    return text

async def process_message(message: aio_pika.abc.AbstractIncomingMessage):
    """Triggered instantly whenever RabbitMQ pushes an event."""
    async with message.process(): # Automatically acknowledges the message on completion
        payload = json.loads(message.body.decode())
        data = payload.get("data", {})
        operation = data.get("operation")
        doc_info = data.get("doc", {})
        doc_id = doc_info.get("id")

        # CRITICAL: Ignore updates so we don't trigger an infinite loop when we patch the status
        if operation == "update":
            return

        print(f"⚡ Event Triggered: Document {doc_id} (Operation: {operation})")

        try:
            # Fetch full document with depth=1 to get resolved emails
            res = await asyncio.to_thread(api_request, "GET", f"/communications/{doc_id}?depth=1")
            doc = res.json()
            
            # Idempotency guard: Ensure we haven't already processed this
            status = doc.get("status")
            if status in ["sent", "processing"]:
                print(f"  -> Document {doc_id} is already {status}. Skipping.\n")
                return

            # Mark processing
            await asyncio.to_thread(api_request, "PATCH", f"/communications/{doc_id}", json={"status": "processing"})

            # Extract emails
            to_addresses = [to["value"]["email"] for to in doc.get("tos", []) if isinstance(to.get("value"), dict) and "email" in to["value"]]

            if not to_addresses:
                await asyncio.to_thread(api_request, "PATCH", f"/communications/{doc_id}", json={"status": "failed"})
                return

            # Send email
            print("  -> Transmitting via SMTP...")
            msg = EmailMessage()
            msg.set_content(serialize_slate_to_text(doc.get("body")))
            msg['Subject'] = doc.get("subject", "No Subject")
            msg['From'] = EMAIL_FROM
            msg['To'] = ", ".join(to_addresses)
            
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.send_message(msg)

            # Mark sent
            await asyncio.to_thread(api_request, "PATCH", f"/communications/{doc_id}", json={"status": "sent"})
            print("  -> Delivery confirmed! Marked as 'sent'.\n")

        except Exception as e:
            print(f"Error processing document {doc_id}: {e}")
            try:
                await asyncio.to_thread(api_request, "PATCH", f"/communications/{doc_id}", json={"status": "failed"})
            except:
                pass

async def main():
    print("Starting MZinga Event-Driven Worker...")
    # Initial authentication
    await asyncio.to_thread(authenticate)
    
    # Connect robust handles reconnects if RabbitMQ restarts
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    async with connection:
        channel = await connection.channel()
        
        # Limit to processing 1 message at a time per worker instance
        await channel.set_qos(prefetch_count=1)

        # Declare the exchange matching MZinga's exact settings
        exchange = await channel.declare_exchange(
            EXCHANGE_NAME, 
            aio_pika.ExchangeType.TOPIC, 
            durable=True,
            internal=True,
            auto_delete=False
        )

        # Declare durable queue and bind it
        queue = await channel.declare_queue(QUEUE_NAME, durable=True)
        await queue.bind(exchange, routing_key=ROUTING_KEY)

        print("Connected! Silently waiting for messages from RabbitMQ...\n")
        await queue.consume(process_message)

        # Keep the connection open indefinitely
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())