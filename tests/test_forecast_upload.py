import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from lazyresearch.api import create_app
from lazyresearch.forecast import Forecast, backtest


class ForecastUploadTests(unittest.TestCase):
    def test_zip_keeps_binary_members_and_returns_one_attachment(self):
        with tempfile.TemporaryDirectory() as tmp, TestClient(create_app(Path(tmp))) as client:
            def upload(extra):
                stream = io.BytesIO()
                with zipfile.ZipFile(stream, "w") as archive:
                    archive.writestr("nested/train.csv","date,sales\n2020-01-01,2")
                    for i in range(15):
                        archive.writestr(f"note{i}.txt","hello")
                    archive.writestr(extra,bytes([0,255,1]))
                return client.post("/research/files?name=data.zip",content=stream.getvalue())
            result = upload("weights.bin")
            self.assertEqual(result.status_code,201)
            self.assertEqual(result.json()["name"],"data.zip")
            import json
            manifest = Path(tmp)/"research"/"uploads"/result.json()["id"]/"meta.json"
            self.assertEqual(len(json.loads(manifest.read_text())["members"]),17)
            member = json.loads(manifest.read_text())["members"][-1]
            self.assertEqual(member["archive_path"], "weights.bin")
            self.assertEqual((manifest.parent.parent/member["id"]/"content").read_bytes(), bytes([0,255,1]))

    def test_holdout_labels_cannot_affect_earlier_fold(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/"inputs").mkdir()
            frame = pd.DataFrame({"day":pd.date_range("2020-01-01",periods=75),"store":"a",
                                  "sales":[i%7+1 for i in range(75)]})
            path = root/"inputs"/"train"
            frame.to_csv(path,index=False)
            args = Forecast(file_id="train",date="day",target="sales",groups=["store"],horizon=7,fold=1)
            task = {"files":[{"id":"train","name":"train.csv"}]}
            score = backtest(root,task,args)
            self.assertAlmostEqual(score["baseline"],0)
            frame.loc[frame.index[-7:],"sales"]=1000
            frame.to_csv(path,index=False)
            self.assertEqual(score,backtest(root,task,args))
