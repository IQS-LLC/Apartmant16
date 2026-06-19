import multiprocessing
import os

bind = "0.0.0.0:8000"
backlog = 2048

workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"
worker_connections = 1000
timeout = 30
keepalive = 2

max_requests = 1000
max_requests_jitter = 50

loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
accesslog = "-"
errorlog = "-"

proc_name = "plc_django"

daemon = False
pidfile = "/tmp/gunicorn.pid"

# Removed hardcoded user/group — let Docker handle this
tmp_upload_dir = None

keyfile = None
certfile = None