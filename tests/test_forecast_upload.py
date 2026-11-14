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
    def test_zip_returns_separate_upload_references_and_rejects_bad_member(self):
        with tempfile.TemporaryDirectory() as tmp, TestClient(create_app(Path(tmp))) as client:
            def upload(extra):
                stream = io.BytesIO()
                with zipfile.ZipFile(stream, "w") as archive:
                    archive.writestr("nested/train.csv","date,sales\n2020-01-01,2")
                    archive.writestr(extra,b"id,sales\n1,0")
                return client.post("/research/files?name=data.zip",content=stream.getvalue())
            result = upload("test.csv")
            self.assertEqual(result.status_code,201)
            self.assertEqual([f["name"] for f in result.json()["files"]],["train.csv","test.csv"])
            uploads = Path(tmp)/"research"/"uploads"
            before = set(uploads.iterdir())
            self.assertEqual(upload("bad.exe").status_code,422)
            self.assertEqual(before,set(uploads.iterdir()))

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
