import json
import traceback

from agent_runtime import plan_recipes
from repository import Repository


def process_job(repository: Repository, message: dict) -> None:
    run_id = str(message["runId"])
    if not repository.start_recipe_job(run_id):
        return
    try:
        result = plan_recipes(
            repository,
            user_id=str(message["userId"]),
            latitude=float(message["latitude"]),
            longitude=float(message["longitude"]),
            max_stops=int(message["maxStops"]),
            max_miles=float(message["maxMiles"]),
        )
        repository.complete_recipe_job(run_id, result)
    except Exception as error:
        print(json.dumps({
            "event": "recipe_job_failed",
            "runId": run_id,
            "type": type(error).__name__,
            "message": str(error),
            "traceback": traceback.format_exc(),
        }))
        if type(error).__name__ == "StructuredOutputValidationError":
            message = "Recipe planning could not produce a valid result. Please try again."
        else:
            message = "Recipe planning failed. Please try again."
        repository.fail_recipe_job(run_id, message)


def handler(event, _context):
    repository = Repository()
    for record in event.get("Records", []):
        process_job(repository, json.loads(record["body"]))
