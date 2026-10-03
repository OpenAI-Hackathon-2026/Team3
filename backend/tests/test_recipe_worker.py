import unittest
from unittest.mock import patch

from recipe_worker import process_job


class FakeRepository:
    def __init__(self, starts=True):
        self.starts = starts
        self.completed = []
        self.failed = []

    def start_recipe_job(self, run_id):
        return self.starts

    def complete_recipe_job(self, run_id, result):
        self.completed.append((run_id, result))

    def fail_recipe_job(self, run_id, message):
        self.failed.append((run_id, message))


MESSAGE = {
    "runId": "run-1",
    "userId": "recipient-1",
    "latitude": 35.22,
    "longitude": -80.84,
    "maxStops": 2,
    "maxMiles": 3,
}


class RecipeWorkerTests(unittest.TestCase):
    @patch("recipe_worker.plan_recipes", return_value={"plans": [], "explanation": "No match."})
    def test_worker_completes_persisted_job(self, planner):
        repository = FakeRepository()

        process_job(repository, MESSAGE)

        self.assertEqual(repository.completed[0][0], "run-1")
        self.assertEqual(repository.failed, [])
        planner.assert_called_once()

    @patch("recipe_worker.plan_recipes", side_effect=RuntimeError("provider unavailable"))
    def test_worker_records_failure(self, _planner):
        repository = FakeRepository()

        process_job(repository, MESSAGE)

        self.assertEqual(repository.completed, [])
        self.assertEqual(repository.failed[0][0], "run-1")
        self.assertNotIn("provider unavailable", repository.failed[0][1])

    @patch("recipe_worker.plan_recipes")
    def test_terminal_job_is_not_reprocessed(self, planner):
        repository = FakeRepository(starts=False)

        process_job(repository, MESSAGE)

        planner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
