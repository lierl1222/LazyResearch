import json
from pathlib import Path
import tempfile
import unittest

import httpx
from fastapi.testclient import TestClient

from lazyresearch.api import create_app
from lazyresearch.configuration import ModelConfig
from lazyresearch.research_service import ResearchService, Submission
from lazyresearch.research_tools import ReadMaterial, read_material
from lazyresearch.science.gateway import ScienceGateway


class SessionAcceptance(unittest.TestCase):
    def test_shared_memory_and_evidence_through_http(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = ModelConfig()
            config.cloud.enabled = True
            config.cloud.base_url = "https://test.invalid"
            config.cloud.model = "test"
            prompts = []
            def respond(request):
                prompts.append(json.loads(json.loads(request.content)["messages"][1]["content"]))
                return httpx.Response(200, json={"choices":[{"message":{"content":json.dumps(
                    {"answer":"结论 "+prompts[-1]["question"]})}}],"usage":{"prompt_tokens":14,"completion_tokens":6}})
            service = ResearchService(root/"research", config, lambda c,r,b,**kw:
                ScienceGateway(c,r,b,httpx.MockTransport(respond),**kw))
            with TestClient(create_app(root,research_service=service)) as client:
                files = [client.post("/research/files",params={"name":name},content=body).json()
                         for name,body in [("sample.csv",b"signal,y\n1,0"),("note.md","采样间隔".encode())]]
                task = Submission(goal="评估采样误差",domain="水声通信",file_ids=[f["id"] for f in files],
                                  budget={"max_cloud_requests":4,"max_llm_input_tokens":60000,"max_llm_output_tokens":30000})
                run = service.create(task)
                url = "/research/runs/"+run
                registry = service.registry(run)
                for stage in ("plan","hypothesis","execution","validation","revision"):
                    service.emit(registry,stage,round=1,summary="步骤 "+stage)
                material = registry.get("task")
                self.assertEqual(read_material(registry.root,material,ReadMaterial(file_id=files[1]["id"]))["excerpt"],"采样间隔")
                for stage,msg in [(None,"参考频率19"),("execution","误差2"),("validation","需要校准"),("revision","下一轮怎么做")]:
                    result = client.post(url+"/messages",json={"stage_id":stage,"round_id":1 if stage else None,"message":msg})
                    self.assertEqual(result.status_code,200,result.text)
                self.assertIn("参考频率19",str(prompts[1]["recent_dialogue"]))
                self.assertIn("误差2",str(prompts[2]["recent_dialogue"]))
                self.assertIn("需要校准",str(prompts[3]["recent_dialogue"]))
                self.assertEqual(prompts[3]["recent_dialogue"][-1],
                                 {"user":"需要校准","assistant":"结论 需要校准"})
                self.assertNotEqual(prompts[1]["node_records"],prompts[2]["node_records"])
                self.assertIn("execution",str(prompts[2]["round_evidence"]))
                self.assertEqual(prompts[1]["domain"],"水声通信")
                service.emit(registry,"validation",round=2,summary="第二次验证")
                for _ in range(2):
                    snap = client.get(url).json()
                    self.assertEqual(snap["conversation_id"],run)
                    self.assertEqual(len(snap["exchanges"]),4)
                    self.assertEqual(len(next(s for s in snap["workflow"] if s["id"]=="validation")["records"]),2)
                    self.assertEqual(snap["budget"]["input_tokens"],56)
                    self.assertEqual(snap["budget"]["cloud_requests"],4)
                self.assertEqual(client.post(url+"/messages",json={"message":"再问"}).status_code,409)
                other = service.create(task)
                self.assertEqual(client.get("/research/runs/"+other).json()["exchanges"],[])
                self.assertEqual(client.post("/research/runs/"+other+"/messages",json={"message":"另一项任务"}).status_code,200)
                self.assertEqual(prompts[-1]["memory"],[])
