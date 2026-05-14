import os
import time
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

MONGO_URI = os.getenv("MONGODB_URI")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", 5))

def main():
    print("Starting MZinga Email Worker...")
    print("Connecting to MongoDB...")
    
    # Connect to the database
    client = MongoClient(MONGO_URI)
    
    # Payload CMS usually defaults the database name to "mzinga" or whatever is in the URI
    db = client.get_database("mzinga") 
    communications_col = db.get_collection("communications")

    print(f"Successfully connected! Polling every {POLL_INTERVAL} seconds for pending emails...\n")

    while True:
        try:
            # 1. Find ONE pending email and atomically mark it as 'processing'
            # find_one_and_update prevents race conditions if we had 10 workers running at once!
            email_doc = communications_col.find_one_and_update(
                {"status": "pending"},
                {"$set": {"status": "processing"}},
                return_document=True
            )

            if email_doc:
                doc_id = email_doc.get("_id")
                subject = email_doc.get("subject", "No Subject")
                print(f"[{time.strftime('%X')}] Picked up email: '{subject}' (ID: {doc_id})")
                
                # 2. Simulate the work of securely sending an email
                print("  -> Processing payload and formatting HTML...")
                time.sleep(1) # Fake processing delay
                print("  -> Transmitting via SMTP...")
                time.sleep(1) # Fake network delay
                
                # 3. Mark as successfully sent
                communications_col.update_one(
                    {"_id": doc_id},
                    {"$set": {"status": "sent"}}
                )
                print("  -> Delivery confirmed! Marked as 'sent' in database.\n")
            
        except Exception as e:
            print(f"Error during processing: {e}")

        # Rest before checking the queue again
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()