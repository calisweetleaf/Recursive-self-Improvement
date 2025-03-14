# Code Citations

This document lists all third-party code used in this project with appropriate attributions.

## Format Uptime Function

The following function is adapted from the PyBorg project:

```python
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
```

Source: https://github.com/cr0sis/PyBorg/blob/14df62482b569d3bdb094dcd3e188d7b57cad794/utility.py

License: unknown
