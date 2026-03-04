# agent.py — DistilGPT-2 LLM integration for weather geofence data summarization
#
# The LLM used is DistilGPT-2 (via Hugging Face Transformers), matching the
# approach taken in the Weather-MCP reference project.

from __future__ import annotations

from typing import Optional, Tuple

from transformers import AutoModelForCausalLM, AutoTokenizer

_MODEL_NAME = "distilgpt2"
_tokenizer: Optional[AutoTokenizer] = None
_model: Optional[AutoModelForCausalLM] = None


def _load_model() -> Tuple[AutoModelForCausalLM, AutoTokenizer]:
    """Lazily load (and cache) the DistilGPT-2 model and tokenizer."""
    global _tokenizer, _model
    if _tokenizer is None or _model is None:
        _tokenizer = AutoTokenizer.from_pretrained(_MODEL_NAME)
        _tokenizer.pad_token_id = _tokenizer.eos_token_id
        _model = AutoModelForCausalLM.from_pretrained(_MODEL_NAME)
    return _model, _tokenizer


def generate_summary(weather_data: str, max_new_tokens: int = 100) -> str:
    """
    Generate a natural-language summary of *weather_data* using DistilGPT-2.

    Args:
        weather_data:   A plain-text description of the weather / geofence situation.
        max_new_tokens: Maximum number of *new* tokens to generate (prompt excluded).

    Returns:
        The model-generated text (prompt stripped, special tokens removed).
    """
    model, tokenizer = _load_model()
    prompt = (
        f"Weather Data:\n\n{weather_data}\n\n"
        "Instruction: Summarize the weather data into a concise and natural language response."
    )
    inputs = tokenizer.encode(prompt, return_tensors="pt")
    attention_mask = inputs.ne(tokenizer.pad_token_id).long()
    outputs = model.generate(
        inputs,
        max_new_tokens=max_new_tokens,
        num_return_sequences=1,
        do_sample=True,
        temperature=0.7,
        top_p=0.9,
        pad_token_id=tokenizer.eos_token_id,
        attention_mask=attention_mask,
    )
    # Decode only the newly generated tokens (exclude the prompt)
    generated_tokens = outputs[0][len(inputs[0]):]
    return tokenizer.decode(generated_tokens, skip_special_tokens=True)


def summarize_location(
    lat: float,
    lon: float,
    inside: bool,
    event: Optional[str],
    severity: Optional[str],
) -> str:
    """
    Build a plain-text weather description for a location and run it through
    DistilGPT-2 to produce a concise summary.

    Args:
        lat:      Latitude of the queried point.
        lon:      Longitude of the queried point.
        inside:   Whether the point is inside an active weather polygon.
        event:    Name of the weather event (if inside), e.g. "Tornado Warning".
        severity: Severity string (if inside), e.g. "Severe".

    Returns:
        A natural-language summary string.
    """
    if inside and event:
        weather_data = (
            f"Location ({lat}, {lon}) is inside an active weather alert zone.\n"
            f"Event: {event}\n"
            f"Severity: {severity or 'Unknown'}"
        )
    else:
        weather_data = (
            f"Location ({lat}, {lon}) is not inside any active weather alert zone. "
            "No significant weather events are currently affecting this area."
        )
    return generate_summary(weather_data)
