"""Offline multimodal replacements for the optional Codex vision and planning calls."""

import time

from laya_runtime.client import ModelClient, image_url
from PIL import Image

from .gold97_vision import SCREEN_PROMPT
from .journey_strategy_provider import JourneyStrategyProvider, validate_plan


class LocalScreenReader:
    def __init__(self):
        self.client = ModelClient()
        self.model = self.client.model
        self.timeout = self.client.timeout

    def model_input(self, frame):
        return {"model": self.model, "prompt": SCREEN_PROMPT,
                "image": {"width": int(frame.shape[1]), "height": int(frame.shape[0])}}

    def describe(self, frame):
        schema = {"type": "object", "additionalProperties": False, "properties": {
            "screen_text": {"type": "array", "items": {"type": "string"}},
            "mode": {"type": "string", "enum": ["battle", "menu", "dialogue", "overworld", "unknown"]},
            "walkable_directions": {"type": "array", "items": {
                "type": "string", "enum": ["up", "down", "left", "right"]}},
            "uncertainty": {"type": "string"}},
            "required": ["screen_text", "mode", "walkable_directions", "uncertainty"]}
        start = time.monotonic()
        value, usage = self.client.structured([
            {"role": "system", "content": SCREEN_PROMPT},
            {"role": "user", "content": [{"type": "image_url", "image_url": {
                "url": image_url(Image.fromarray(frame[:, :, :3]))}}]}], schema, max_tokens=512)
        import jsonschema
        jsonschema.validate(value, schema)
        value["screen_text"] = value["screen_text"][:12]
        if value["mode"] != "overworld":
            value["walkable_directions"] = []
        value["usage"] = {**usage, "latency_ms": (time.monotonic() - start) * 1000}
        return value


class LocalJourneyProvider(JourneyStrategyProvider):
    def __init__(self):
        self.client = ModelClient()
        self.model = self.client.model
        self.timeout = self.client.timeout

    def plan(self, payload):
        request = self.model_input(payload)
        start = time.monotonic()
        value, usage = self.client.structured([
            {"role": "user", "content": request["prompt"]}], request["output_schema"], max_tokens=512)
        return validate_plan(value, payload), {
            **usage, "latency_ms": (time.monotonic() - start) * 1000}
