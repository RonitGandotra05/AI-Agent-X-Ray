"""Check an installed distribution without importing the repository checkout.

Run with an isolated interpreter after installing a built wheel or sdist:
    python -I scripts/smoke_installed.py [--server] [--langchain]
"""

import argparse
import importlib.util
import json
import sys
from importlib.metadata import distribution
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", action="store_true")
    parser.add_argument("--langchain", action="store_true")
    args = parser.parse_args()

    import xray_sdk
    from xray_sdk import XRayClient, XRayRun, XRayStep
    from xray_shared import Summarizer

    package = distribution("xray-sdk")
    assert package.version == xray_sdk.__version__
    base_dependencies = [entry for entry in package.requires or [] if ";" not in entry]
    assert base_dependencies == ["requests>=2.31.0"], base_dependencies
    source_root = Path(__file__).resolve().parents[1]
    assert source_root not in Path(xray_sdk.__file__).resolve().parents
    assert Path(xray_sdk.__file__).with_name("py.typed").is_file()
    assert importlib.util.find_spec("xray_sdk.integrations.langchain") is not None
    assert importlib.util.find_spec("xray_sdk.integrations.crewai") is not None
    assert not any(name in sys.modules for name in ("flask", "openai", "anthropic", "langchain_core", "crewai"))

    run = XRayRun("installed_package", description="Validate the installed SDK.")
    run.add_step(XRayStep("transform", 1, inputs={"value": 2}, outputs={"value": 4}))
    payload = run.to_dict()
    assert json.loads(json.dumps(payload))["steps"][0]["outputs"] == {"value": 4}
    assert Summarizer().ensure_within_budget({"value": 4}) == {"value": 4}
    client = XRayClient("http://localhost:5000")
    if hasattr(client, "close"):
        client.close()

    if args.server:
        from xray_api.app import create_app

        app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "XRAY_API_KEY": None,
        })
        with app.test_client() as api:
            payload["analyze"] = False
            response = api.post("/api/ingest", json=payload)
            assert response.status_code == 201, response.get_json()
            run_id = response.get_json()["run_id"]
            response = api.get("/api/runs/" + run_id)
            assert response.status_code == 200, response.get_json()
            assert response.get_json()["steps"][0]["step_name"] == "transform"

    if args.langchain:
        from langchain_core.runnables import RunnableLambda
        from xray_sdk.integrations.langchain import XRayCallbackHandler

        handler = XRayCallbackHandler(pipeline_name="installed_langchain")
        chain = RunnableLambda(lambda value: value + 1)
        assert chain.invoke(3, config={"callbacks": [handler]}) == 4
        captured = handler.get_run().to_dict()
        assert captured["pipeline_name"] == "installed_langchain"
        assert len(captured["steps"]) == 1
        assert captured["steps"][0]["outputs"] == {"output": 4}

    print("Installed xray-sdk {} smoke check passed{}".format(
        package.version, " (including optional integrations)" if args.server or args.langchain else "",
    ))


if __name__ == "__main__":
    main()
