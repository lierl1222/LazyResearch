import tempfile
import unittest
from pathlib import Path
from lazyresearch.science.data import generate_demo
from lazyresearch.research_service import Submission, ResearchService
from lazyresearch.research_tools import profile, tabular, Profile, Tabular
from lazyresearch.configuration import ModelConfig

class TabularIntegrationTests(unittest.TestCase):
    def test_uploaded_csv_runs_training_and_statistical_review(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"data.csv"
            generate_demo(path,400,42)
            service=ResearchService(Path(folder)/"runs",ModelConfig())
            id=service.create(Submission(goal="Validate classification",csv_text=path.read_text(),target="y"))
            registry=service.registry(id)
            task=registry.get("task")
            evidence=profile(registry.root,task,Profile())
            self.assertTrue(evidence["profile"]["features"])
            result=tabular(registry.root,task,Tabular(experiment_type="nonlinear_model"))
            self.assertIn(result["verdict"],{"supported","refuted","inconclusive"})
            self.assertIn("average_precision",result["metrics"])
            self.assertIn("review",result)
