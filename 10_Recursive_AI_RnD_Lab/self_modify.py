import os
import sys
import json
import time
import logging
import hashlib
import subprocess
import importlib.util
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
from flask import Flask, render_template

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("ai_system.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("self_modifying_ai")

app = Flask(__name__)

# Add this before the route definitions
@app.template_filter('format_uptime')
def format_uptime(seconds):
    """Format uptime in seconds to a human-readable string."""
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    
    if days > 0:
        return f"{int(days)}d {int(hours)}h {int(minutes)}m"
    elif hours > 0:
        return f"{int(hours)}h {int(minutes)}m {int(seconds)}s"
    elif minutes > 0:
        return f"{int(minutes)}m {int(seconds)}s"
    else:
        return f"{int(seconds)}s"

class SelfModifyingAI:
    """
    A self-modifying AI system that can alter its own code and use various models.
    """
    
    def __init__(self, 
                 main_script: str = "AI_Main.py",
                 backup_dir: str = "backups",
                 config_file: str = "config.json",
                 max_versions: int = 10):
        """
        Initialize the self-modifying AI system.
        
        Args:
            main_script: Path to the main AI script that will be modified
            backup_dir: Directory to store backups of previous versions
            config_file: Path to the configuration file
            max_versions: Maximum number of version backups to keep
        """
        self.main_script = main_script
        self.backup_dir = Path(backup_dir)
        self.config_file = config_file
        self.max_versions = max_versions
        self.version = self._get_current_version()
        
        # Ensure backup directory exists
        self.backup_dir.mkdir(exist_ok=True, parents=True)
        
        # Load configuration
        self.config = self._load_config()
        
        # Initialize main script if it doesn't exist
        if not Path(self.main_script).exists():
            self._initialize_main_script()
        
        # Add plugin loading
        self.load_plugins()
        
        logger.info(f"Self-modifying AI initialized. Current version: {self.version}")

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from the specified JSON file."""
        if not Path(self.config_file).exists():
            raise FileNotFoundError(f"Configuration file {self.config_file} not found")
        
        with open(self.config_file, "r") as f:
            return json.load(f)

    def _get_current_version(self) -> int:
        """Determine the current version by examining backup files or return 1 if none exist."""
        if not self.backup_dir.exists():
            return 1
            
        backup_files = list(self.backup_dir.glob(f"{Path(self.main_script).stem}_v*.py"))
        if not backup_files:
            return 1
            
        versions = [int(f.stem.split('_v')[1]) for f in backup_files]
        return max(versions) + 1 if versions else 1

    def _initialize_main_script(self) -> None:
        """Create the initial main script if it doesn't exist."""
        initial_code = """# AI_Main.py - Initial Version
import logging
logger = logging.getLogger("ai_main")

def main():
    logger.info("AI system running initial version")
    print("AI system initialized and ready for evolution")
    return {"status": "initialized", "actions": []}

if __name__ == "__main__":
    result = main()
    print(f"Execution complete: {result}")
"""
        with open(self.main_script, "w") as f:
            f.write(initial_code)
        logger.info(f"Initialized {self.main_script} with default code")

    def backup_current_version(self) -> str:
        """
        Create a backup of the current main script.
        
        Returns:
            Path to the backup file
        """
        if not Path(self.main_script).exists():
            logger.warning(f"{self.main_script} does not exist, nothing to backup")
            return ""
        
        # Create backup filename with version number
        backup_filename = self.backup_dir / f"{Path(self.main_script).stem}_v{self.version}.py"
        
        # Copy current script to backup
        with open(self.main_script, "r") as src:
            current_code = src.read()
            
        with open(backup_filename, "w") as dest:
            dest.write(current_code)
            
        logger.info(f"Backed up {self.main_script} to {backup_filename}")
        
        # Clean up old backups if we exceed max_versions
        self._cleanup_old_backups()
        
        return str(backup_filename)

    def _cleanup_old_backups(self) -> None:
        """Remove oldest backups if we exceed the maximum number of versions to keep."""
        backup_files = list(self.backup_dir.glob(f"{Path(self.main_script).stem}_v*.py"))
        if len(backup_files) <= self.max_versions:
            return
            
        # Sort by version number and remove oldest
        backup_files.sort(key=lambda f: int(f.stem.split('_v')[1]))
        for old_file in backup_files[:len(backup_files) - self.max_versions]:
            os.remove(old_file)
            logger.info(f"Removed old backup: {old_file}")

    def generate_new_code(self) -> str:
        """
        Generate new code for the AI using the specified model service.
        
        Returns:
            New code as a string
        """
        try:
            # Load existing code
            with open(self.main_script, "r") as f:
                current_code = f.read()
                
            # Create a prompt for the model
            prompt = f"""
            # Current AI code:
            ```python
            {current_code}
            ```
            
            # Task: Improve this code by adding new capabilities or optimizing existing ones.
            # Return only valid Python code for the new version.
            """
            
            # Call the model service
            logger.info(f"Generating new code using model service: {self.config['model_service']}")
            result = subprocess.run(
                [self.config['model_service'], self.config['model_endpoint'], prompt],
                capture_output=True,
                text=True,
                timeout=60  # 60 second timeout
            )
            
            if result.returncode != 0:
                logger.error(f"Model execution failed: {result.stderr}")
                return current_code
                
            # Extract the code from the model's response
            new_code = self._extract_code_from_response(result.stdout)
            
            # Validate that the returned code is valid Python
            if not self._validate_python_code(new_code):
                logger.warning("Generated code failed validation, using current code")
                return current_code
                
            logger.info("Successfully generated new code")
            return new_code
            
        except Exception as e:
            logger.error(f"Error generating new code: {str(e)}")
            # Fall back to a safe modification if the model fails
            return self._create_fallback_modification()

    def _extract_code_from_response(self, response: str) -> str:
        """Extract code from the model's response, handling various formatting."""
        # Look for code blocks
        if "```python" in response and "```" in response:
            # Extract code between python code blocks
            start = response.find("```python") + len("```python")
            end = response.find("```", start)
            if end > start:
                return response[start:end].strip()

        return response.strip()

    def _validate_python_code(self, code: str) -> bool:
        """
        Check if the generated code is valid Python syntax.
        
        Args:
            code: Python code to validate
            
        Returns:
            True if code is valid Python, False otherwise
        """
        try:
            compile(code, '<string>', 'exec')
            return True
        except SyntaxError:
            logger.error("Generated code contains syntax errors")
            return False

    def _create_fallback_modification(self) -> str:
        """Create a simple but safe modification to the existing code."""
        with open(self.main_script, "r") as f:
            current_code = f.read()
        
        # Add a timestamped comment and a new logging statement
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        return f"""# AI_Main.py - Modified at {timestamp}
# Fallback modification due to model generation failure
import logging
import time
logger = logging.getLogger("ai_main")

def main():
    logger.info("AI system running fallback modified version")
    print(f"AI evolving gradually - Timestamp: {time.time()}")
    
    # Add new capability - system information
    import platform
    system_info = {{
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "processor": platform.processor()
    }}
    
    logger.info(f"System information: {{system_info}}")
    return {{"status": "evolving", "system_info": system_info}}

if __name__ == "__main__":
    result = main()
    print(f"Execution complete: {{result}}")
"""

    def self_modify(self) -> Tuple[bool, str]:
        """
        Modify the main AI script with newly generated code.
        
        Returns:
            Tuple of (success_flag, message)
        """
        try:
            # First, backup the current version
            backup_path = self.backup_current_version()
            if not backup_path:
                return False, "Failed to create backup"
            
            # Generate new code
            new_code = self.generate_new_code()
            
            # Calculate hashes to check if the code actually changed
            original_hash = None
            if Path(self.main_script).exists():
                with open(self.main_script, "rb") as f:
                    original_hash = hashlib.md5(f.read()).hexdigest()
                    
            new_hash = hashlib.md5(new_code.encode()).hexdigest()
            
            # Only write if the code actually changed
            if original_hash != new_hash:
                with open(self.main_script, "w") as f:
                    f.write(new_code)
                self.version += 1
                logger.info(f"Successfully modified {self.main_script} to version {self.version}")
                return True, f"Modified to version {self.version}"
            else:
                logger.info("No changes detected in generated code")
                return False, "No changes detected in generated code"
                
        except Exception as e:
            logger.error(f"Error in self_modify: {str(e)}")
            return False, f"Error: {str(e)}"

    def run_self_written_code(self) -> Tuple[bool, Dict[str, Any]]:
        """
        Execute the modified AI main script in a controlled environment.
        
        Returns:
            Tuple of (success_flag, execution_result)
        """
        try:
            logger.info(f"Executing {self.main_script}")
            
            # Run in a subprocess to isolate execution
            result = subprocess.run(
                [sys.executable, self.main_script],
                capture_output=True,
                text=True,
                timeout=30  # 30 second timeout to prevent infinite loops
            )
            
            if result.returncode == 0:
                logger.info(f"Successfully executed {self.main_script}")
                # Try to parse any JSON output from the script
                try:
                    # Check if output contains JSON
                    output = result.stdout.strip()
                    if output.startswith("{") and output.endswith("}"):
                        execution_result = json.loads(output)
                    else:
                        execution_result = {"stdout": output, "stderr": result.stderr}
                except json.JSONDecodeError:
                    execution_result = {"stdout": result.stdout, "stderr": result.stderr}
                    
                return True, execution_result
            else:
                logger.error(f"Execution failed: {result.stderr}")
                return False, {"error": result.stderr, "stdout": result.stdout}
                
        except subprocess.TimeoutExpired:
            logger.error(f"Execution of {self.main_script} timed out")
            return False, {"error": "Execution timed out"}
        except Exception as e:
            logger.error(f"Error running self-written code: {str(e)}")
            return False, {"error": str(e)}

    def rollback_to_version(self, version: int) -> bool:
        """
        Rollback to a specific previous version.
        
        Args:
            version: Version number to rollback to
            
        Returns:
            True if rollback successful, False otherwise
        """
        backup_file = self.backup_dir / f"{Path(self.main_script).stem}_v{version}.py"
        if not backup_file.exists():
            logger.error(f"Version {version} not found in backups")
            return False
            
        try:
            # Read backup file
            with open(backup_file, "r") as f:
                backup_code = f.read()
                
            # Write to main script
            with open(self.main_script, "w") as f:
                f.write(backup_code)
                
            logger.info(f"Successfully rolled back to version {version}")
            return True
        except Exception as e:
            logger.error(f"Error during rollback: {str(e)}")
            return False

    def load_plugins(self):
        """Load strategy plugins from the strategy_plugins directory."""
        self.plugins = {}
        plugin_dir = Path(__file__).parent / "strategy_plugins"
        
        if not plugin_dir.exists():
            logger.warning(f"Plugin directory {plugin_dir} not found")
            return
        
        logger.info(f"Scanning for plugins in {plugin_dir}")
        
        for plugin_path in plugin_dir.glob("*.py"):
            if plugin_path.name.startswith("__"):
                continue  # Skip __init__.py and similar files
            
            try:
                plugin_name = plugin_path.stem
                logger.info(f"Loading plugin: {plugin_name}")
                
                # Load the plugin module
                spec = importlib.util.spec_from_file_location(plugin_name, plugin_path)
                if spec is None:
                    logger.warning(f"Failed to create spec for {plugin_path}")
                    continue
                    
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # Check for handle function
                if hasattr(module, "handle"):
                    self.plugins[plugin_name] = module.handle
                    logger.info(f"Registered plugin {plugin_name} with 'handle' function")
                # Check for register_plugin function
                elif hasattr(module, "register_plugin"):
                    plugin_func = module.register_plugin()
                    if callable(plugin_func):
                        self.plugins[plugin_name] = plugin_func
                        logger.info(f"Registered plugin {plugin_name} via 'register_plugin' function")
                    else:
                        logger.warning(f"Plugin {plugin_name} register_plugin() did not return a callable")
                else:
                    logger.warning(f"Plugin {plugin_name} has no 'handle' or 'register_plugin' function")
                    
            except Exception as e:
                logger.error(f"Error loading plugin {plugin_path}: {str(e)}")

    def get_current_code(self) -> str:
        """Get the current code of the main script."""
        with open(self.main_script, "r") as f:
            return f.read()

@app.route('/code_view')
def code_view():
    current_code = ai_system.get_current_code()
    return render_template('code_view.html', current_code=current_code)

def main():
    """Main entry point for the self-modifying AI system."""
    try:
        # Initialize the self-modifying AI system
        global ai_system
        ai_system = SelfModifyingAI(
            main_script="AI_Main.py",
            backup_dir="ai_backups",
            config_file="config.json",
            max_versions=10
        )
        
        # Perform self-modification
        modified, modify_message = ai_system.self_modify()
        logger.info(f"Self-modification result: {modify_message}")
        
        if modified:
            # Run the modified code
            success, result = ai_system.run_self_written_code()
            if success:
                logger.info(f"Execution result: {result}")
            else:
                logger.error(f"Execution failed: {result}")
                
                # Automatically rollback on failure if this isn't the first version
                if ai_system.version > 1:
                    logger.info(f"Attempting automatic rollback to version {ai_system.version - 1}")
                    if ai_system.rollback_to_version(ai_system.version - 1):
                        logger.info("Automatic rollback successful")
                    else:
                        logger.error("Automatic rollback failed")
        else:
            logger.info("No modifications made, skipping execution")
            
    except Exception as e:
        logger.critical(f"Critical error in main: {str(e)}")
        return 1
        
    return 0

if __name__ == "__main__":
    sys.exit(main())