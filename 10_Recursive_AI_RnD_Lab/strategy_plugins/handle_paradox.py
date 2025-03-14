# clearly structured example plugin (strategy_plugins/handle_paradox.py)

# Complete implementation

def handle(prompt):
    """
    Detect paradoxical statements in the input prompt.
    
    Args:
        prompt (str): The input prompt to check
        
    Returns:
        str or None: Error message if paradox detected, None otherwise
    """
    paradoxes = [
        "lying right now",
        "this statement is false",
        "am i telling the truth when i say i'm lying",
        "the next statement is true. the previous statement is false",
        "i always lie",
        "the following sentence is true. the previous sentence is false"
    ]
    
    prompt_lower = prompt.lower()
    for paradox in paradoxes:
        if paradox in prompt_lower:
            return ("Paradox detected: Self-referential contradiction found. "
                    "Halting recursive processing to prevent infinite loop.")
            
    # Check for more complex paradox patterns
    if "sentence is" in prompt_lower and ("false" in prompt_lower or "true" in prompt_lower) and "this" in prompt_lower:
        return ("Potential liar paradox detected. Processing with caution to avoid recursive loops.")
    
    return None