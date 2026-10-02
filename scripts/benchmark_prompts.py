"""Reproduce deterministic prompt-size measurements without a paid provider.

The baseline counts were measured against repository commit 27732d9 using the
same ten-step fixture and no previous-window context (a conservative baseline).
Character counts are not model token counts or live inference measurements.
"""

import json

from xray_api.agents.analyzer import XRayAnalyzer
from xray_sdk import XRayRun, XRayStep
from xray_shared import Summarizer


class MeasuringAdapter:
    def __init__(self):
        self.calls = 0
        self.characters = 0

    def chat_completion_with_usage(self, messages, **kwargs):
        self.calls += 1
        self.characters += sum(len(message["content"]) for message in messages)
        return json.dumps({
            "faulty_step": None, "faulty_step_order": None, "severity": "ok",
            "reason": "No observed contradiction.", "suggestion": None, "all_issues": [],
        }), {}


def main():
    run = XRayRun("benchmark", description="Pass a value through ten stages.")
    for order in range(1, 11):
        run.add_step(XRayStep(f"step_{order}", order, inputs={"value": order - 1},
                             outputs={"value": order}, description="Add one to the value."))
    adapter = MeasuringAdapter()
    result = XRayAnalyzer(adapter=adapter).analyze_run(run.to_dict())
    original_chars = 19327
    large = {"items": [{"id": i, "data": "x" * 500} for i in range(400)]}
    sample = Summarizer(sample_size=10).ensure_within_budget(large)
    print(json.dumps({
        "baseline_commit": "27732d9",
        "ten_steps": {
            "baseline_calls": 9, "current_calls": adapter.calls,
            "baseline_prompt_characters": original_chars,
            "current_prompt_characters": adapter.characters,
            "prompt_character_reduction_percent": round(100 * (1 - adapter.characters / original_chars), 1),
            "provider_token_usage_available": result["token_usage_available"],
        },
        "sample_400_records": {
            "original_json_characters": len(json.dumps(large)),
            "sampled_json_characters": len(json.dumps(sample)),
            "original_record_count": sample["items_total_count"],
        },
    }, indent=2))


if __name__ == "__main__":
    main()
