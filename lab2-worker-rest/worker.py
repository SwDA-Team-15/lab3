import os
import time
import requests
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv()

# Configuration
API_URL = os.getenv("MZINGA_API_URL")
ADMIN_EMAIL = os.getenv("MZINGA_ADMIN_EMAIL")
ADMIN_PASSWORD = os.getenv("MZINGA_ADMIN_PASSWORD")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", 5))
SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", 1025))
EMAIL_FROM = os.getenv("EMAIL_FROM", "worker@mzinga.io")

# Global JWT Token
token = None

def authenticate():
    """Authenticates with the MZinga API and stores the JWT token."""
    global token
    print("Authenticating with MZinga REST API...")
    res = requests.post(f"{API_URL}/users/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    res.raise_for_status()
    token = res.json().get("token")
    print("Successfully authenticated.\n")

def api_request(method, endpoint, **kwargs):
    """Wrapper for requests that injects the Bearer token and handles 401s."""
    global token
    if not token:
        authenticate()
    
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    
    url = f"{API_URL}{endpoint}"
    res = requests.request(method, url, headers=headers, **kwargs)
    
    # Handle token expiry
    if res.status_code == 401:
        print("Token expired. Re-authenticating...")
        authenticate()
        headers["Authorization"] = f"Bearer {token}"
        res = requests.request(method, url, headers=headers, **kwargs)
        
    res.raise_for_status()
    return res

def serialize_slate_to_text(body):
    """A basic helper to extract raw text from Payload's Slate AST JSON."""
    text = ""
    if not body: return text
    for node in body:
        if 'children' in node:
            for child in node['children']:
                text += child.get('text', '') + " "
        text += "\n"
    return text

def main():
    print("Starting MZinga REST API Worker...")
    print(f"Polling for pending emails every {POLL_INTERVAL} seconds...\n")
    
    while True:
        try:
            # 1. Fetch pending documents with depth=1 to resolve user relationships
            res = api_request("GET", "/communications?where[status][equals]=pending&depth=1")
            docs = res.json().get("docs", [])
            
            for doc in docs:
                doc_id = doc["id"]
                subject = doc.get("subject", "No Subject")
                print(f"[{time.strftime('%X')}] Picked up email: '{subject}' (ID: {doc_id})")
                
                # 2. Mark as processing immediately
                api_request("PATCH", f"/communications/{doc_id}", json={"status": "processing"})
                
                # 3. Extract emails directly from the resolved payload (no separate DB query!)
                to_addresses = []
                for to in doc.get("tos", []):
                    # Check if 'value' is a resolved dictionary containing an email
                    if isinstance(to.get("value"), dict) and "email" in to["value"]:
                        to_addresses.append(to["value"]["email"])
                        
                if not to_addresses:
                    print(f"  -> No valid 'To' addresses found. Marking failed.")
                    api_request("PATCH", f"/communications/{doc_id}", json={"status": "failed"})
                    continue
                    
                # 4. Serialize body and prepare email
                body_text = serialize_slate_to_text(doc.get("body"))
                msg = EmailMessage()
                msg.set_content(body_text)
                msg['Subject'] = subject
                msg['From'] = EMAIL_FROM
                msg['To'] = ", ".join(to_addresses)
                
                # 5. Send via SMTP
                print("  -> Transmitting via SMTP...")
                with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                    server.send_message(msg)
                    
                # 6. Mark as successfully sent via REST API
                api_request("PATCH", f"/communications/{doc_id}", json={"status": "sent"})
                print("  -> Delivery confirmed! Marked as 'sent'.\n")
                
        except Exception as e:
            print(f"Error during polling cycle: {e}")
            
        # Rest before checking the queue again
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()