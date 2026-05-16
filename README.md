# MZinga Lab 3: Observability with OpenTelemetry

Welcome to the third part of the MZinga Email Worker Lab! In this stage, we introduce **Observability** to our Python worker. We will implement the three pillars of observability—Logs, Metrics, and Traces—using OpenTelemetry, Prometheus, and Jaeger.

## 🔭 The Three Pillars of Observability

1. **Structured Logs:** Replaces plain text logs with JSON objects (using `structlog`).
2. **Metrics:** Aggregated numeric measurements (e.g., `emails_processed_total`) exported to **Prometheus**.
3. **Traces:** Distributed tracking showing time spent in each function, exported to **Jaeger**.

## 🚀 Step 0: Clone the Repository

First, clone this repository to your local machine and open the folder:

```bash
git clone [https://github.com/SwDA-Team-15/lab3.git](https://github.com/SwDA-Team-15/lab3.git)
cd lab3
```

## 🚀 Step 1: Start the Infrastructure

In addition to our database and message broker, we now need observability tools.

1. Navigate to the CMS folder:

   ```bash
   cd mzinga-apps
   ```

2. **Crucial:** Ensure you have the `prometheus.yml` file in this folder to allow Prometheus to scrape metrics.

3. Start all services:

   ```bash
   docker compose up database messagebus cache jaeger prometheus -d
   ```

4. Run Mailhog (if not already running):

   ```bash
   docker run -d -p 1025:1025 -p 8025:8025 --name mailhog mailhog/mailhog
   ```

## 🐍 Step 2: Setup the Python Worker

1. Open a **new terminal window** and navigate to the worker folder:

   ```bash
   cd lab3-worker-observable
   ```

2. Activate your virtual environment:
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

3. **Configure Environment:** Ensure your `.env` contains:

   ```env
   OTEL_SERVICE_NAME=email-worker
   OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
   PROMETHEUS_PORT=8000 
   ```

4. Install dependencies and start:

   ```bash
   pip install -r requirements.txt
   python worker.py
   ```

## 🧪 Step 3: Test and Observe

1. **Trigger:** Create a new email in MZinga Admin ([http://localhost:3000/admin](http://localhost:3000/admin)).
2. **Logs:** Check your terminal for JSON formatted logs.
3. **Traces:** Open **Jaeger** at [http://localhost:16686](http://localhost:16686). Select `email-worker` service to see the "waterfall" of your function calls.
4. **Metrics:** Open **Prometheus** at [http://localhost:9090](http://localhost:9090). Query `emails_processed_total` and check the **Graph** tab.
