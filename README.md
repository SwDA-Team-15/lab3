# MZinga Lab 2: REST API & Event-Driven Worker

Welcome to the second part of the MZinga Email Worker Lab! In this stage, we evolve our architecture from direct database coupling to more robust integration patterns: **REST API** and **Message Queues (RabbitMQ)**.

## Architecture Evolution

- **State 2 (REST API):** The worker no longer accesses MongoDB directly. It communicates with MZinga exclusively via HTTP requests adhering to the published API contract.
- **State 3 (Event-Driven):** Polling is removed. MZinga pushes tasks to the worker instantly using **RabbitMQ**, ensuring zero-latency processing.

## 🚀 Step 0: Clone the Repository

First, clone this repository to your local machine and open the folder:

```bash
git clone https://github.com/SwDA-Team-15/lab2.git
cd lab2
```

## 🚀 Step 1: Start the Infrastructure

Ensure Docker is running. We need the database and the message broker (RabbitMQ) active.

1. Navigate to the CMS folder:

   ```bash
   cd mzinga-apps
   ```

2. Start the services:

   ```bash
   docker compose up database messagebus cache -d
   ```

3. Run Mailhog:

   ```bash
   docker run -d -p 1025:1025 -p 8025:8025 --name mailhog mailhog/mailhog
   ```

### ⚠️ Troubleshooting: Database Authentication Errors

If you encounter authentication errors (or MZinga fails to connect to the database), your Docker volumes might have stale credentials from previous lab sessions.
To completely reset the database and start fresh, run:

```bash
docker compose down -v
docker compose up database messagebus cache -d
```

*(Note: The `-v` flag deletes the database volumes, meaning you will need to register a new Admin user when you open the MZinga admin panel).*
## ⚙️ Step 2: Configure MZinga

To enable RabbitMQ notifications (only for **lab2-worker-events**), uncomment two lines in your `.env` file in the `mzinga-apps` folder:

```bash
RABBITMQ_URL=amqp://guest:guest@localhost/
HOOKSURL_COMMUNICATIONS_AFTERCHANGE=rabbitmq
```

*Note: Restart MZinga after making changes (`npm run dev`).*

## 🐍 Step 3: Setup the Python Worker

Configure the environment for the new worker logic.

1. Open a **new, separate terminal window** and navigate to the REST worker folder:

   ```bash
   cd lab2-worker-rest
   ```

   or, for the event-driven version:

   ```bash
   cd lab2-worker-events
   ```

2. Create and activate a virtual environment:
   - **Windows:**

     ```bash
     python -m venv .venv
     .\.venv\Scripts\activate
     ```

   - **Mac/Linux:**

     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```

3. Install the required Python libraries:

   ```bash
   pip install -r requirements.txt
   ```

4. Start the worker:

   ```bash
   python worker.py
   ```

*Leave this terminal open! It will print out a message when it connects to the MZinga API or RabbitMQ.*

## 🧪 Step 4: Test the Flow

Let's watch the decoupled systems work together:

1. Open your browser and go to **<http://localhost:3000/admin>** and **<http://localhost:8025/>**
2. **Log in as Admin.**
3. Navigate to **Users** (you should already have one from Lab 1).
4. Navigate to **Communications** and click **Create New**.
5. Fill out the Subject, Body, and select your dummy user in the "To" field.
6. Click **Save**.

**The Result:** Watch your Python worker terminal! Within 5 seconds (or instantly for events), it will detect the new email, print the subject, and mark it as sent. If you refresh the page in your browser, you will see the status dropdown has automatically changed from **Pending** to **Sent**. You will also find the newly sent email in the Mailhog inbox at <http://localhost:8025/>.
