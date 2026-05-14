import os
import time
import requests
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv

# --- New imports for Observability ---
import structlog
from opentelemetry import trace, metrics
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from prometheus_client import start_http_server

load_dotenv()

# ==========================================
# CONFIGURATION (From Lab 2)
# ==========================================
API_URL = os.getenv("MZINGA_API_URL", "http://localhost:3000/api")
ADMIN_EMAIL = os.getenv("MZINGA_ADMIN_EMAIL")
ADMIN_PASSWORD = os.getenv("MZINGA_ADMIN_PASSWORD")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", 5))
SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", 1025))
EMAIL_FROM = os.getenv("EMAIL_FROM", "worker@mzinga.io")

token = None

# ==========================================
# OBSERVABILITY INITIALIZATION (Lab 3)
# ==========================================
structlog.configure(
    processors=[
        structlog.processors.dict_tracebacks,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)
logger = structlog.get_logger()

resource = Resource.create({"service.name": os.getenv("OTEL_SERVICE_NAME", "email-worker")})

# 1. Traces (Jaeger)
trace.set_tracer_provider(TracerProvider(resource=resource))
otlp_exporter = OTLPSpanExporter(endpoint=f"{os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT', 'http://localhost:4318')}/v1/traces")
trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(otlp_exporter))
tracer = trace.get_tracer(__name__)

# Automatically instruments requests.get and requests.patch
RequestsInstrumentor().instrument() 

# 2. Metrics (Prometheus)
prometheus_port = int(os.getenv("PROMETHEUS_PORT", 8000))
start_http_server(prometheus_port)
metric_reader = PrometheusMetricReader()
metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[metric_reader]))
meter = metrics.get_meter(__name__)

# Create counters and histograms
emails_processed_total = meter.create_counter("emails_processed_total", description="Total number of emails processed")
worker_poll_total = meter.create_counter("worker_poll_total", description="Total number of API polls")
email_processing_duration = meter.create_histogram("email_processing_duration_seconds")
smtp_send_duration = meter.create_histogram("smtp_send_duration_seconds")

# ==========================================
# CORE LOGIC (Instrumented)
# ==========================================
def authenticate():
    global token
    logger.info("authenticating_with_mzinga")
    res = requests.post(f"{API_URL}/users/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    res.raise_for_status()
    token = res.json().get("token")
    logger.info("authenticated_successfully")

def api_request(method, endpoint, **kwargs):
    global token
    if not token:
        authenticate()
    
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    
    url = f"{API_URL}{endpoint}"
    res = requests.request(method, url, headers=headers, **kwargs)
    
    if res.status_code == 401:
        logger.warning("token_expired_reauthenticating")
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

def process_communication(doc):
    """Helper function to process a single communication document."""
    doc_id = doc["id"]
    subject = doc.get("subject", "No Subject")
    start_time = time.time()

    # Start a root span for the tracer
    with tracer.start_as_current_span("process_communication") as span:
        span.set_attribute("doc_id", doc_id)
        logger.info("picked_up_email", subject=subject, doc_id=doc_id)

        try:
            api_request("PATCH", f"/communications/{doc_id}", json={"status": "processing"})
            
            to_addresses = []
            for to in doc.get("tos", []):
                if isinstance(to.get("value"), dict) and "email" in to["value"]:
                    to_addresses.append(to["value"]["email"])
                    
            if not to_addresses:
                logger.warning("no_valid_addresses_found", doc_id=doc_id)
                api_request("PATCH", f"/communications/{doc_id}", json={"status": "failed"})
                
                # Increment failed metric
                emails_processed_total.add(1, {"status": "failed", "recipient_count": 0})
                span.set_attribute("status", "failed")
                return
                
            body_text = serialize_slate_to_text(doc.get("body"))
            msg = EmailMessage()
            msg.set_content(body_text)
            msg['Subject'] = subject
            msg['From'] = EMAIL_FROM
            msg['To'] = ", ".join(to_addresses)
            
            # Start a child span to measure SMTP speed
            with tracer.start_as_current_span("send_email") as smtp_span:
                smtp_start = time.time()
                logger.info("transmitting_via_smtp", doc_id=doc_id, recipients=len(to_addresses))
                
                with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                    server.send_message(msg)
                    
                # Record SMTP duration histogram
                smtp_duration = time.time() - smtp_start
                smtp_send_duration.record(smtp_duration)
                
            api_request("PATCH", f"/communications/{doc_id}", json={"status": "sent"})
            logger.info("delivery_confirmed", doc_id=doc_id, status="sent")
            
            # Increment success metric
            emails_processed_total.add(1, {"status": "sent", "recipient_count": len(to_addresses)})
            span.set_attribute("status", "sent")
            
        except Exception as e:
            # Tracer catches exceptions automatically
            span.record_exception(e)
            span.set_status(trace.status.Status(trace.status.StatusCode.ERROR, str(e)))
            logger.error("processing_failed", doc_id=doc_id, error=str(e))
            
            emails_processed_total.add(1, {"status": "error", "recipient_count": 0})
            try:
                api_request("PATCH", f"/communications/{doc_id}", json={"status": "failed"})
            except:
                pass

        finally:
            # Record total processing duration
            total_duration = time.time() - start_time
            email_processing_duration.record(total_duration)

def main():
    logger.info("worker_started", poll_interval=POLL_INTERVAL)
    
    while True:
        try:
            res = api_request("GET", "/communications?where[status][equals]=pending&depth=1")
            docs = res.json().get("docs", [])
            
            # Increment polling counter
            worker_poll_total.add(1, {"result": "success", "docs_found": len(docs)})
            
            for doc in docs:
                process_communication(doc)
                
        except Exception as e:
            logger.error("polling_cycle_error", error=str(e))
            worker_poll_total.add(1, {"result": "error", "docs_found": 0})
            
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()