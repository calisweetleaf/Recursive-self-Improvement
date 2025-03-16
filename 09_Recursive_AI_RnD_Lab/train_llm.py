import os
import sys
import json
import time
import logging
import argparse
import subprocess
import hashlib
import threading
import shutil
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Union
from dataclasses import dataclass, asdict, field
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levellevelname)s - %(message)s',
    handlers=[
        logging.FileHandler("model_training.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("model_trainer")

@dataclass
class TrainingConfig:
    """Configuration for model training."""
    model_name: str
    base_model: str = ""  # Leave empty for starting a new model
    training_dataset: str = ""
    validation_dataset: str = ""
    output_dir: str = "models"
    epochs: int = 3
    batch_size: int = 4
    learning_rate: float = 2e-5
    max_length: int = 2048
    gradient_accumulation_steps: int = 1
    save_strategy: str = "epoch"
    warmup_ratio: float = 0.03
    logging_steps: int = 10
    evaluation_strategy: str = "epoch"
    load_best_model_at_end: bool = True
    backend: str = "ollama"  # ollama, llamacpp, etc.
    model_format: str = "gguf"  # gguf, safetensors, etc.
    custom_params: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding empty values."""
        result = {}
        for key, value in asdict(self).items():
            if value != "" and value is not None:
                if isinstance(value, dict) and not value:  # Skip empty dictionaries
                    continue
                result[key] = value
        return result
    
    def to_cli_args(self) -> List[str]:
        """Convert configuration to command line arguments."""
        args = []
        for key, value in self.to_dict().items():
            if isinstance(value, bool):
                if value:
                    args.append(f"--{key}")
            elif isinstance(value, dict):
                for k, v in value.items():
                    args.append(f"--{key}.{k}={v}")
            else:
                args.append(f"--{key}={value}")
        return args
    
    @classmethod
    def from_file(cls, config_file: str) -> 'TrainingConfig':
        """Load configuration from a JSON file."""
        try:
            with open(config_file, 'r') as f:
                config_data = json.load(f)
                return cls(**config_data)
        except Exception as e:
            logger.error(f"Failed to load config from {config_file}: {str(e)}")
            raise

@dataclass
class TrainingMetrics:
    """Metrics collected during training."""
    epoch: int
    loss: float
    learning_rate: float
    eval_loss: Optional[float] = None
    perplexity: Optional[float] = None
    accuracy: Optional[float] = None
    timestamp: float = field(default_factory=time.time)

@dataclass
class TrainingSession:
    """Information about a training session."""
    id: str
    model_name: str
    config: TrainingConfig
    start_time: float
    end_time: Optional[float] = None
    metrics: List[TrainingMetrics] = field(default_factory=list)
    status: str = "initializing"  # initializing, running, completed, failed
    error_message: Optional[str] = None
    output_model_path: Optional[str] = None
    
    def duration(self) -> float:
        """Calculate the duration of the training session."""
        end = self.end_time or time.time()
        return end - self.start_time
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = asdict(self)
        result["duration"] = self.duration()
        result["metrics"] = [asdict(m) for m in self.metrics]
        result["config"] = self.config.to_dict()
        return result
    
    def add_metric(self, metric: TrainingMetrics) -> None:
        """Add a training metric to the session."""
        self.metrics.append(metric)
    
    def save(self, output_dir: str = "training_logs") -> str:
        """Save the session information to a JSON file."""
        os.makedirs(output_dir, exist_ok=True)
        filename = os.path.join(output_dir, f"{self.id}.json")
        
        with open(filename, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)
        
        return filename

class ModelTrainer:
    """Class for training ML models with various backends."""
    
    def __init__(self, config: TrainingConfig):
        """
        Initialize the model trainer.
        
        Args:
            config: Configuration for training
        """
        self.config = config
        self.session_id = self._generate_session_id()
        self.session = TrainingSession(
            id=self.session_id,
            model_name=config.model_name,
            config=config,
            start_time=time.time()
        )
        self.training_process = None
        self.output_handler_thread = None
        self.stop_output_handler = threading.Event()
        
        # Ensure output directory exists
        os.makedirs(config.output_dir, exist_ok=True)
        
        # Set up training logs directory
        self.logs_dir = os.path.join("training_logs", self.session_id)
        os.makedirs(self.logs_dir, exist_ok=True)
        
        # Set up file handlers for this specific training session
        self.log_file = os.path.join(self.logs_dir, "training.log")
        file_handler = logging.FileHandler(self.log_file)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        logger.addHandler(file_handler)
        
        logger.info(f"Initialized training session {self.session_id} for model '{config.model_name}'")
    
    def _generate_session_id(self) -> str:
        """Generate a unique session ID."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_data = f"{timestamp}_{self.config.model_name}_{os.getpid()}"
        hash_obj = hashlib.md5(unique_data.encode())
        return f"{timestamp}_{hash_obj.hexdigest()[:8]}"
    
    def _prepare_training_data(self) -> bool:
        """
        Prepare and validate training data.
        
        Returns:
            True if data preparation was successful, False otherwise
        """
        try:
            # Check if training dataset exists
            if not self.config.training_dataset:
                logger.error("No training dataset specified")
                self.session.status = "failed"
                self.session.error_message = "No training dataset specified"
                return False
            
            if not os.path.exists(self.config.training_dataset):
                logger.error(f"Training dataset not found: {self.config.training_dataset}")
                self.session.status = "failed"
                self.session.error_message = f"Training dataset not found: {self.config.training_dataset}"
                return False
            
            # If validation dataset is specified, check if it exists
            if self.config.validation_dataset and not os.path.exists(self.config.validation_dataset):
                logger.error(f"Validation dataset not found: {self.config.validation_dataset}")
                self.session.status = "failed"
                self.session.error_message = f"Validation dataset not found: {self.config.validation_dataset}"
                return False
            
            # Validate dataset format based on file extension
            dataset_path = Path(self.config.training_dataset)
            if dataset_path.suffix.lower() == '.json':
                # Validate JSON format
                try:
                    with open(dataset_path, 'r') as f:
                        data = json.load(f)
                        
                    # Basic structure validation for different formats
                    if isinstance(data, list):
                        logger.info(f"Dataset contains {len(data)} examples")
                    elif isinstance(data, dict) and "data" in data:
                        logger.info(f"Dataset contains {len(data['data'])} examples")
                    else:
                        logger.warning("Dataset structure is non-standard, verify compatibility with your model")
                        
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON in dataset: {str(e)}")
                    self.session.status = "failed"
                    self.session.error_message = f"Invalid JSON in dataset: {str(e)}"
                    return False
            
            # For other formats (like .txt, .csv, etc.), we could add additional validation
            
            logger.info(f"Successfully validated training data: {self.config.training_dataset}")
            return True
            
        except Exception as e:
            logger.error(f"Error during data preparation: {str(e)}")
            self.session.status = "failed"
            self.session.error_message = f"Error during data preparation: {str(e)}"
            return False
    
    def _output_handler(self, process):
        """
        Handle the output from the training process.
        
        Args:
            process: The subprocess running the training
        """
        try:
            # Open output files for logging
            stdout_log = open(os.path.join(self.logs_dir, "stdout.log"), 'w')
            stderr_log = open(os.path.join(self.logs_dir, "stderr.log"), 'w')
            
            def process_line(line, is_stderr=False):
                # Write to appropriate log file
                if is_stderr:
                    stderr_log.write(line + '\n')
                    stderr_log.flush()
                    logger.warning(f"STDERR: {line}")
                else:
                    stdout_log.write(line + '\n')
                    stdout_log.flush()
                    
                    # Try to extract metrics from the output
                    try:
                        # This pattern matching would depend on the backend's output format
                        # Example for a line like: "Epoch 1/3: loss=2.345, lr=0.00002"
                        if "Epoch" in line and "loss=" in line:
                            # Extract epoch
                            epoch_part = line.split("Epoch ")[1].split(":")[0].split("/")[0]
                            epoch = int(epoch_part.strip())
                            
                            # Extract loss
                            loss_part = line.split("loss=")[1].split(",")[0]
                            loss = float(loss_part.strip())
                            
                            # Extract learning rate if available
                            lr = self.config.learning_rate
                            if "lr=" in line:
                                lr_part = line.split("lr=")[1].split(",")[0]
                                lr = float(lr_part.strip())
                            
                            # Add metric to session
                            metric = TrainingMetrics(
                                epoch=epoch,
                                loss=loss,
                                learning_rate=lr
                            )
                            self.session.add_metric(metric)
                            logger.info(f"Recorded metrics: epoch={epoch}, loss={loss}, lr={lr}")
                    except Exception as e:
                        # Just log the error but don't crash the output handler
                        logger.debug(f"Failed to extract metrics from line: {str(e)}")
            
            # Process stdout
            for line in iter(process.stdout.readline, b''):
                if self.stop_output_handler.is_set():
                    break
                decoded_line = line.decode('utf-8').rstrip()
                if decoded_line:
                    process_line(decoded_line)
            
            # Process stderr
            for line in iter(process.stderr.readline, b''):
                if self.stop_output_handler.is_set():
                    break
                decoded_line = line.decode('utf-8').rstrip()
                if decoded_line:
                    process_line(decoded_line, is_stderr=True)
                    
        except Exception as e:
            logger.error(f"Error in output handler: {str(e)}")
        finally:
            # Close log files
            stdout_log.close()
            stderr_log.close()
    
    def _train_with_ollama(self) -> bool:
        """
        Train model using Ollama backend.
        
        Returns:
            True if training was successful, False otherwise
        """
        try:
            # Construct the Ollama create command
            cmd = ["ollama", "create", self.config.model_name]
            
            # If base model is specified, add it
            if self.config.base_model:
                cmd.extend(["--from", self.config.base_model])
            
            # Add the training dataset
            cmd.extend(["-f", self.config.training_dataset])
            
            # Add any custom parameters
            for key, value in self.config.custom_params.items():
                if isinstance(value, bool) and value:
                    cmd.append(f"--{key}")
                else:
                    cmd.append(f"--{key}={value}")
            
            logger.info(f"Starting Ollama training with command: {' '.join(cmd)}")
            
            # Start the training process
            self.session.status = "running"
            self.training_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
                universal_newlines=False
            )
            
            # Start output handler in a separate thread
            self.output_handler_thread = threading.Thread(
                target=self._output_handler,
                args=(self.training_process,)
            )
            self.output_handler_thread.start()
            
            # Wait for training to complete
            returncode = self.training_process.wait()
            
            # Stop the output handler
            self.stop_output_handler.set()
            if self.output_handler_thread.is_alive():
                self.output_handler_thread.join(timeout=5)
            
            # Check if training was successful
            if returncode == 0:
                self.session.status = "completed"
                self.session.end_time = time.time()
                
                # In Ollama, models are stored internally
                self.session.output_model_path = f"{self.config.model_name}"
                
                logger.info(f"Training completed successfully. Model available as '{self.config.model_name}' in Ollama")
                return True
            else:
                self.session.status = "failed"
                self.session.error_message = f"Training process exited with code {returncode}"
                self.session.end_time = time.time()
                
                logger.error(f"Training failed with exit code {returncode}")
                return False
                
        except Exception as e:
            logger.error(f"Error in Ollama training: {str(e)}")
            self.session.status = "failed"
            self.session.error_message = f"Error in Ollama training: {str(e)}"
            self.session.end_time = time.time()
            return False