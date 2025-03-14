# Self-Modifying AI System

## Overview

This example implements a self-modifying AI system that can evolve its own code using various models and services. It's part of the larger [Recursive Self-Improvement](https://github.com/calisweetleaf/Recursive-self-Improvement) project.

## Installation

1. Clone the main repository:

   ```sh
   git clone https://github.com/calisweetleaf/Recursive-self-Improvement.git
   cd Recursive-self-Improvement/10_Working_Examples_And_Proof_Code
   ```

2. Install the required dependencies:

   ```sh
    pip install -r requirements.txt

3. Modify config.json to whatever local services your running
   


## ⚙️ Configuration File (`config.json`)

The `config.json` file allows you to configure the Recursive AI Daemon to connect to your local Ollama model and define key recursion behavior parameters. This makes setup fast, flexible, and easy to adapt to different local environments.

### Example `config.json`:

```json
{
  "model_name": "Gemma3-4b",
  "api_url": "http://localhost:11434/api/generate",
  "max_recursion_depth": 5,
  "log_directory": "./logs",
  "snapshot_directory": "./snapshots",
  "strategy_plugin_dir": "./strategy_plugins"
}
