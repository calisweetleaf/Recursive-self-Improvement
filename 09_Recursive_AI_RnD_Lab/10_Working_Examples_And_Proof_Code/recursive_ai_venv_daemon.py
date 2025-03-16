# Placeholder for recursive_ai_venv_daemon.py
from flask import Flask, render_template, jsonify, request, redirect, url_for, flash, Response
import os
import sys
import json
import time
import logging
import subprocess
import threading
import queue
import datetime
import socket
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from functools import wraps
import traceback

# Import the SelfModifyingAI class from the main module
# This assumes that both files are in the same directory
try:
    from self_modify import SelfModifyingAI
except ImportError as e:
    logger = logging.getLogger("ai_flask_server")
    logger.error(f"Failed to import SelfModifyingAI: {e}")
    # Define a placeholder class if the import fails
    class SelfModifyingAI:
        def __init__(self, *args, **kwargs):
            pass
        def trigger_evolution(self, *args, **kwargs):
            logger.warning("Using placeholder SelfModifyingAI class - evolution not available")
            return False
                
        def backup(self, *args, **kwargs):
            logger.warning("Using placeholder SelfModifyingAI class - backup not available")
            return False
                
        def rollback(self, *args, **kwargs):
            logger.warning("Using placeholder SelfModifyingAI class - rollback not available")
            return False
                
        def get_current_code(self, *args, **kwargs):
            logger.warning("Using placeholder SelfModifyingAI class - code retrieval not available")
            return ""
                
        def get_version_history(self, *args, **kwargs):
            logger.warning("Using placeholder SelfModifyingAI class - version history not available")
            return []

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("ai_server.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("ai_flask_server")

# Flask application setup
app = Flask(__name__, 
            template_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates"),
            static_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), "static"))

# Secret key for session management and CSRF protection
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24).hex())

# Configuration with fallbacks
app.config.update(
    AI_MAIN_SCRIPT=os.environ.get("AI_MAIN_SCRIPT", "AI_Main.py"),
    BACKUP_DIR=os.environ.get("BACKUP_DIR", "ai_backups"),
    MODEL_NAME=os.environ.get("MODEL_NAME", "default_model"),
    MAX_VERSIONS=int(os.environ.get("MAX_VERSIONS", "10")),
    LOG_DIR=os.environ.get("LOG_DIR", "logs"),
    DEBUG=os.environ.get("FLASK_DEBUG", "False").lower() in ("true", "1", "t"),
    AUTH_ENABLED=os.environ.get("AUTH_ENABLED", "False").lower() in ("true", "1", "t"),
    AUTH_USERNAME=os.environ.get("AUTH_USERNAME", "admin"),
    AUTH_PASSWORD=os.environ.get("AUTH_PASSWORD", "changeme")
)

# Ensure directories exist
Path(app.config["BACKUP_DIR"]).mkdir(exist_ok=True, parents=True)
Path(app.config["LOG_DIR"]).mkdir(exist_ok=True, parents=True)

# Initialize template directory if it doesn't exist
template_dir = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates"))
template_dir.mkdir(exist_ok=True, parents=True)

# Initialize static directory if it doesn't exist
static_dir = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "static"))
static_dir.mkdir(exist_ok=True, parents=True)

# Initialize the AI system
ai_system = SelfModifyingAI(
    main_script=app.config["AI_MAIN_SCRIPT"],
    backup_dir=app.config["BACKUP_DIR"],
    config_file="config.json",
    max_versions=app.config["MAX_VERSIONS"]
)

# Global variables for system monitoring
system_status = {
    "last_modification": None,
    "current_version": 1,
    "last_execution_result": None,
    "is_healthy": True,
    "cpu_usage": 0.0,
    "memory_usage": 0.0,
    "uptime": 0
}

# Queue for real-time log streaming
log_queue = queue.Queue(maxsize=1000)  # Limit queue size to prevent memory issues
log_handler = None

@dataclass
class SystemMetrics:
    """Data class for system metrics."""
    timestamp: float
    cpu_percent: float
    memory_percent: float
    disk_usage_percent: float
    network_bytes_sent: int
    network_bytes_recv: int
    temperature: Optional[float] = None  # Some systems may not have temperature sensors

# Store metrics history
metrics_history: List[SystemMetrics] = []
MAX_METRICS_HISTORY = 1000  # Limit to prevent memory issues

def setup_log_handler():
    """Set up a special log handler that also puts logs in our queue for streaming."""
    global log_handler
    
    class QueueHandler(logging.Handler):
        def emit(self, record):
            try:
                # Format the log message
                msg = self.format(record)
                # Put in queue, don't block if queue is full
                try:
                    log_queue.put_nowait({
                        "timestamp": datetime.datetime.now().isoformat(),
                        "level": record.levelname,
                        "message": msg
                    })
                except queue.Full:
                    # If queue is full, remove oldest item and try again
                    try:
                        log_queue.get_nowait()
                        log_queue.put_nowait({
                            "timestamp": datetime.datetime.now().isoformat(),
                            "level": record.levelname,
                            "message": msg
                        })
                    except (queue.Empty, queue.Full):
                        pass  # Give up if still having issues
            except Exception:
                self.handleError(record)
    
    # Create and add the handler to both loggers
    log_handler = QueueHandler()
    log_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    
    # Add to root logger to catch all logs
    root_logger = logging.getLogger()
    root_logger.addHandler(log_handler)
    
    # Add to our specific loggers
    logging.getLogger("ai_flask_server").addHandler(log_handler)
    logging.getLogger("self_modifying_ai").addHandler(log_handler)

# Call this during initialization
setup_log_handler()

def auth_required(f):
    """Decorator for routes that require authentication."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not app.config["AUTH_ENABLED"]:
            return f(*args, **kwargs)
        
        auth = request.authorization
        if auth and auth.username == app.config["AUTH_USERNAME"] and auth.password == app.config["AUTH_PASSWORD"]:
            return f(*args, **kwargs)
        
        return Response(
            'Authentication required', 
            401,
            {'WWW-Authenticate': 'Basic realm="Login Required"'}
        )
    
    return decorated_function

def update_system_metrics():
    """Update system metrics in the background."""
    try:
        import psutil
        
        while True:
            try:
                # Get current metrics
                cpu_percent = psutil.cpu_percent(interval=1)
                memory = psutil.virtual_memory()
                disk = psutil.disk_usage('/')
                net_io = psutil.net_io_counters()
                
                # Get temperature if available
                temperature = None
                if hasattr(psutil, "sensors_temperatures"):
                    temps = psutil.sensors_temperatures()
                    if temps and "coretemp" in temps:
                        temperature = sum(temp.current for temp in temps["coretemp"]) / len(temps["coretemp"])
                
                # Update current status
                system_status["cpu_usage"] = cpu_percent
                system_status["memory_usage"] = memory.percent
                system_status["uptime"] = time.time() - psutil.boot_time()
                
                # Create metrics record
                metrics = SystemMetrics(
                    timestamp=time.time(),
                    cpu_percent=cpu_percent,
                    memory_percent=memory.percent,
                    disk_usage_percent=disk.percent,
                    network_bytes_sent=net_io.bytes_sent,
                    network_bytes_recv=net_io.bytes_recv,
                    temperature=temperature
                )
                
                # Add to history, maintaining max size
                metrics_history.append(metrics)
                if len(metrics_history) > MAX_METRICS_HISTORY:
                    metrics_history.pop(0)
                
                # Wait before next update
                time.sleep(5)
                
            except Exception as e:
                logger.error(f"Error updating system metrics: {str(e)}")
                time.sleep(10)  # Wait longer if there was an error
                
    except ImportError:
        logger.warning("psutil not installed. System metrics will not be available.")
        # Just update uptime without other metrics
        start_time = time.time()
        while True:
            system_status["uptime"] = time.time() - start_time
            time.sleep(10)

# Start metrics collection in a background thread
metrics_thread = threading.Thread(target=update_system_metrics, daemon=True)
metrics_thread.start()

# Create default template files if they don't exist
def ensure_template_files_exist():
    """Ensure that all necessary template files exist."""
    templates = {
        "base.html": base_template,
        "dashboard.html": dashboard_template,
        # Add other templates as needed
    }
    
    for filename, content in templates.items():
        template_path = template_dir / filename
        if not template_path.exists():
            with open(template_path, 'w') as f:
                f.write(content)
            logger.info(f"Created template file: {template_path}")
    
    # Create CSS file
    css_path = static_dir / "styles.css"
    if not css_path.exists():
        with open(css_path, 'w') as f:
            f.write(css_content)
        logger.info(f"Created CSS file: {css_path}")

ensure_template_files_exist()

# Base template
base_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}AI Control Panel{% endblock %}</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='styles.css') }}">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    {% block head %}{% endblock %}
</head>
<body>
    <nav class="navbar">
        <div class="navbar-brand">
            <h1>AI Control Panel</h1>
        </div>
        <ul class="navbar-menu">
            <li><a href="{{ url_for('home') }}">Dashboard</a></li>
            <li><a href="{{ url_for('code_view') }}">Code Editor</a></li>
            <li><a href="{{ url_for('logs') }}">Logs</a></li>
            <li><a href="{{ url_for('metrics') }}">System Metrics</a></li>
            <li><a href="{{ url_for('config') }}">Configuration</a></li>
        </ul>
    </nav>
    
    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        {% block content %}{% endblock %}
    </div>
    
    <footer>
        <p>Self-Modifying AI System - Running Locally</p>
    </footer>
    
    {% block scripts %}{% endblock %}
</body>
</html>
    """
    
# Dashboard template
dashboard_template = """
{% extends "base.html" %}

{% block title %}AI Control Panel - Dashboard{% endblock %}

{% block content %}
<div class="dashboard">
    <div class="dashboard-header">
        <h2>System Dashboard</h2>
        <div class="system-status">
            <span class="status-label">Status:</span>
            <span class="status-value {% if system_status.is_healthy %}status-healthy{% else %}status-unhealthy{% endif %}">
                {{ "Healthy" if system_status.is_healthy else "Unhealthy" }}
            </span>
        </div>
    </div>
    
    <div class="dashboard-grid">
        <div class="dashboard-card">
            <h3>AI Version</h3>
            <div class="version-info">
                <p>Current Version: <span class="highlight">{{ system_status.current_version }}</span></p>
                <p>Last Modified: <span>{{ system_status.last_modification or "Never" }}</span></p>
            </div>
            <div class="card-actions">
                <button class="btn btn-primary" onclick="location.href='{{ url_for('trigger_evolution') }}'">
                    Trigger Evolution
                </button>
            </div>
        </div>
        
        <div class="dashboard-card">
            <h3>System Resources</h3>
            <div class="resource-meters">
                <div class="meter">
                    <label>CPU Usage</label>
                    <div class="meter-bar">
                        <div class="meter-fill" style="width: {{ system_status.cpu_usage }}%"></div>
                    </div>
                    <span class="meter-value">{{ "%.1f"|format(system_status.cpu_usage) }}%</span>
                </div>
                <div class="meter">
                    <label>Memory Usage</label>
                    <div class="meter-bar">
                        <div class="meter-fill" style="width: {{ system_status.memory_usage }}%"></div>
                    </div>
                    <span class="meter-value">{{ "%.1f"|format(system_status.memory_usage) }}%</span>
                </div>
            </div>
            <p>System Uptime: {{ format_uptime(system_status.uptime) }}</p>
        </div>
    </div>
    
    <div class="dashboard-card full-width">
        <h3>Last Execution Result</h3>
        <div class="execution-result">
            {% if system_status.last_execution_result %}
                <pre>{{ system_status.last_execution_result|tojson(indent=2) }}</pre>
            {% else %}
                <p>No execution results available yet.</p>
            {% endif %}
        </div>
    </div>
    
    <div class="dashboard-card full-width">
        <h3>Version History</h3>
        <div class="version-history">
            <table>
                <thead>
                    <tr>
                        <th>Version</th>
                        <th>Created</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {% for version in version_history %}
                    <tr>
                        <td>{{ version.number }}</td>
                        <td>{{ version.timestamp }}</td>
                        <td>
                            <a href="{{ url_for('view_version', version=version.number) }}">View</a>
                            <a href="{{ url_for('rollback', version=version.number) }}">Rollback</a>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>
{% endblock %}

{% block scripts %}
<script>
    // Auto-refresh the dashboard every 30 seconds
    setTimeout(function() {
        location.reload();
    }, 30000);
</script>
{% endblock %}
    """
    
# CSS for the control panel
css_content = """
   :root {
    --primary-color: #2c3e50;
    --secondary-color: #34495e;
    --accent-color: #3498db;
    --success-color: #2ecc71;
    --warning-color: #f39c12;
    --danger-color: #e74c3c;
   }
   """

@app.route('/')
def home():
    return render_template('dashboard.html', system_status=system_status)

@app.route('/code_view')
def code_view():
    # Implement code view logic
    pass

@app.route('/logs')
def logs():
    # Implement logs view logic
    pass

@app.route('/metrics')
def metrics():
    # Implement metrics view logic
    pass

@app.route('/config')
def config():
    # Implement config view logic
    pass

@app.route('/trigger_evolution')
def trigger_evolution():
    # Implement trigger evolution logic
    pass

@app.route('/rollback/<int:version>')
def rollback(version):
    # Implement rollback logic
    pass

@app.route('/view_version/<int:version>')
def view_version(version):
    # Implement view version logic
    pass