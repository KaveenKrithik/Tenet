"""
prompt_optimizer.py — intercepts and optimizes developer prompts.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

def optimize_prompt(prompt: str, config) -> str:
    """Rewrite the prompt to the most optimized and rule-based prompt for maximum efficiency."""
    try:
        import ollama
        client = ollama.Client(host=config.triage.ollama_host)
        
        system_instruction = (
            "You are a Prompt Optimizer for an AI coding assistant. "
            "Rewrite the user's prompt to be as clear, concise, and rule-based as possible "
            "so that an AI model can understand it easily and execute it with maximum efficiency. "
            "Return ONLY the optimized prompt, with no additional conversational text or explanations. "
            "Original prompt to optimize:\n\n"
        )
        
        logger.info("prompt_optimizer: rewriting prompt for maximum efficiency")
        response = client.generate(
            model=config.triage.ollama_model,
            prompt=f"{system_instruction}{prompt}",
        )
        
        optimized = response.get("response", "").strip() if isinstance(response, dict) else str(response).strip()
        
        if optimized:
            return optimized
            
    except Exception as exc:
        logger.warning("prompt_optimizer: failed to optimize prompt, using original. error: %s", exc)
        
    return prompt
