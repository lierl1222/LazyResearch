import io
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
import httpx
from fastapi.testclient import TestClient
from lazyresearch.api import create_app
from lazyresearch.configuration import ModelConfig
from lazyresearch.research_service import ResearchService
from lazyresearch.science.gateway import ScienceGateway

class ResearchApiTests(unittest.TestCase):
    def test_web_request_runs_real_worker_and_exports_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            config=ModelConfig()
            config.cloud.enabled=True
            config.cloud.base_url="https://example.test"
            config.cloud.model="test"
            def response(request):
                messages=json.loads(request.content)["messages"]
                context=json.loads(messages[1]["content"])
                if "observations" in context:
                    if context["observations"]:
                        answer={"action":"finish","objective_or_conclusion":"Supported on supplied indices","evidence":list(context["observations"])}
                    else:
                        answer={"action":"delegate","objective_or_conclusion":"Test polynomial"}
                elif context["history"]:
                    answer={"action":"return","hypothesis_or_finding":"matches","prediction_or_limitation":"finite indices only"}
                else:
                    answer={"action":"experiment","hypothesis_or_finding":"1+n²","prediction_or_limitation":"matches all indices","tool":"sequence","arguments":{"coefficients":[1,0,1]}}
                return httpx.Response(200,json={"choices":[{"message":{"content":json.dumps(answer)}}],"usage":{"prompt_tokens":100,"completion_tokens":50}})
            service=ResearchService(Path(folder)/"research",config,
                lambda c,r,b,**kw:ScienceGateway(c,r,b,httpx.MockTransport(response),**kw))
            with TestClient(create_app(Path(folder),research_service=service)) as client:
                self.assertEqual(client.post("/research/runs",json={"goal":"bad"}).status_code,422)
                submitted=client.post("/research/runs",json={"goal":"polynomial","sequence":[1,2,5,10]})
                self.assertEqual(submitted.status_code,202)
                id=submitted.json()["id"]
                for _ in range(100):
                    result=client.get("/research/runs/"+id).json()
                    if result["report"]:break
                    time.sleep(.05)
                self.assertEqual(result["status"],"reported",result)
                self.assertEqual(result["budget"]["experiment_count"],1)
                self.assertTrue(any(e["stage"]=="validation" for e in result["events"]))
                self.assertIn("validation",client.get("/research/runs/"+id+"/report").text)
                with zipfile.ZipFile(io.BytesIO(client.get("/research/runs/"+id+"/artifacts").content)) as z:
                    self.assertIn("model_calls.json",z.namelist())
                    self.assertIn("workers/worker-0-0.json",z.namelist())
                self.assertEqual(client.get("/research/runs/not-a-run").status_code,404)
