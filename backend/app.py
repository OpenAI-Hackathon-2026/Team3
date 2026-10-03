import base64
import json
import os
import re
import traceback
import uuid

import boto3
from botocore.exceptions import ClientError

from agent_runtime import extract_donation
from repository import Repository


repository = Repository()
s3 = boto3.client("s3")
places = boto3.client("geo-places")
sqs = boto3.client("sqs")


def response(status: int, body: dict | list):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", "cache-control": "no-store"},
        "body": json.dumps(body),
    }


def body_from(event: dict) -> dict:
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    return json.loads(raw)


def user_id_from(event: dict) -> str:
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    user_id = claims.get("sub")
    if not user_id:
        raise PermissionError("Authentication is required.")
    return user_id


def claims_from(event: dict) -> dict:
    return event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})


def require_fields(data: dict, *fields: str):
    missing = [field for field in fields if data.get(field) in (None, "")]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")


def public_listing(item: dict) -> dict:
    return {key: value for key, value in item.items() if key not in {"pickupAddress", "latitude", "longitude", "createdBy"}}


def geocode(query: str, *, store: bool = False) -> tuple[float, float]:
    result = places.geocode(
        QueryText=query[:200],
        Filter={"IncludeCountries": ["USA"]},
        MaxResults=1,
        IntendedUse="Storage" if store else "SingleUse",
    )
    items = result.get("ResultItems", [])
    if not items or len(items[0].get("Position", [])) != 2:
        raise ValueError("We could not find that location.")
    longitude, latitude = items[0]["Position"]
    return float(latitude), float(longitude)


def recipe_origin(data: dict) -> tuple[float, float]:
    if data.get("latitude") not in (None, "") and data.get("longitude") not in (None, ""):
        latitude, longitude = float(data["latitude"]), float(data["longitude"])
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("Location coordinates are invalid.")
        return latitude, longitude
    postal_code = str(data.get("postalCode", "")).strip()
    if not re.fullmatch(r"\d{5}(?:-\d{4})?", postal_code):
        raise ValueError("Enter a valid US ZIP code.")
    return geocode(f"{postal_code}, USA")


def handler(event, _context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    path = event.get("rawPath", "")
    route_key = event.get("routeKey") or f"{method} {path}"
    try:
        if route_key == "GET /health":
            return response(200, {"status": "ok", "environment": os.environ.get("ENVIRONMENT", "unknown")})

        if route_key == "GET /listings":
            return response(200, {"items": [public_listing(item) for item in repository.list_available()]})

        if route_key == "GET /listings/{listingId}":
            item = repository.get_listing(event.get("pathParameters", {}).get("listingId", ""))
            return response(200, public_listing(item)) if item else response(404, {"error": "Listing not found."})

        user_id = user_id_from(event)

        if route_key == "GET /me":
            profile = repository.profile(user_id)
            return response(200, profile) if profile else response(404, {"error": "Profile not initialized."})

        if route_key == "POST /me/bootstrap":
            data = body_from(event)
            require_fields(data, "displayName", "accountType")
            if data["accountType"] not in {"recipient", "donor"}:
                raise ValueError("Account type must be recipient or donor.")
            if data["accountType"] == "donor" and data.get("address") and (data.get("latitude") in (None, "") or data.get("longitude") in (None, "")):
                data["latitude"], data["longitude"] = geocode(data["address"], store=True)
            claims = claims_from(event)
            return response(201, repository.bootstrap_user(user_id, claims.get("email", ""), data["displayName"], data["accountType"], data.get("organizationName"), data.get("address"), data.get("latitude"), data.get("longitude")))

        if route_key == "POST /listings":
            data = body_from(event)
            require_fields(data, "organizationId", "title", "quantityAvailable", "unit", "pickupEnd")
            item = repository.create_listing(user_id, data.pop("organizationId"), data)
            return response(201, item)

        if route_key == "POST /reservations":
            data = body_from(event)
            require_fields(data, "listingId", "quantity")
            quantity = float(data["quantity"])
            if quantity <= 0:
                raise ValueError("Quantity must be greater than zero.")
            return response(201, repository.create_reservation(user_id, data["listingId"], quantity))

        if route_key == "POST /reservations/bulk":
            data = body_from(event)
            items = data.get("items")
            if not isinstance(items, list):
                raise ValueError("Bundle items are required.")
            return response(201, repository.create_bulk_reservation(user_id, items))

        if route_key == "GET /me/reservations":
            return response(200, {"items": repository.reservations_for_user(user_id)})

        if route_key == "GET /listings/{listingId}/reservations":
            listing_id = event.get("pathParameters", {}).get("listingId", "")
            return response(200, {"items": repository.reservations_for_listing(user_id, listing_id)})

        if route_key == "POST /reservations/{reservationId}/complete":
            reservation_id = event.get("pathParameters", {}).get("reservationId", "")
            return response(200, repository.complete_reservation(user_id, reservation_id))

        if route_key == "POST /uploads":
            data = body_from(event)
            require_fields(data, "contentType", "purpose")
            if data["contentType"] not in {"image/jpeg", "image/png", "image/webp", "audio/webm", "audio/mp4"}:
                raise ValueError("Unsupported upload type.")
            prefix = "temporary-audio" if data["purpose"] == "voice" else f"uploads/{user_id}"
            key = f"{prefix}/{uuid.uuid4()}"
            url = s3.generate_presigned_url(
                "put_object",
                Params={"Bucket": os.environ["MEDIA_BUCKET"], "Key": key, "ContentType": data["contentType"]},
                ExpiresIn=300,
            )
            return response(200, {"uploadUrl": url, "objectKey": key, "expiresIn": 300})

        if route_key == "POST /agent/extract":
            data = body_from(event)
            require_fields(data, "organizationId", "shiftNote")
            return response(200, extract_donation(repository, user_id=user_id, organization_id=data["organizationId"], shift_note=data["shiftNote"][:8000]))

        if route_key == "GET /agent/recipes":
            return response(200, {"items": repository.recipe_jobs_for_user(user_id)})

        if route_key == "GET /agent/recipes/{runId}":
            job = repository.get_recipe_job(user_id, event.get("pathParameters", {}).get("runId", ""))
            return response(200, job) if job else response(404, {"error": "Recipe run not found."})

        if route_key == "POST /agent/recipes":
            data = body_from(event)
            latitude, longitude = recipe_origin(data)
            max_stops = min(max(int(data.get("maxStops", 2)), 1), 4)
            max_miles = min(max(float(data.get("maxMiles", 3)), 0.5), 10)
            job = repository.create_recipe_job(user_id, max_stops=max_stops, max_miles=max_miles)
            try:
                sqs.send_message(
                    QueueUrl=os.environ["RECIPE_JOBS_QUEUE_URL"],
                    MessageBody=json.dumps({
                        "runId": job["runId"],
                        "userId": user_id,
                        "latitude": latitude,
                        "longitude": longitude,
                        "maxStops": max_stops,
                        "maxMiles": max_miles,
                    }),
                )
            except Exception:
                repository.fail_recipe_job(job["runId"], "Recipe planning could not be started. Please try again.")
                raise
            return response(202, job)

        return response(404, {"error": "Route not found."})
    except PermissionError as error:
        return response(403, {"error": str(error)})
    except LookupError as error:
        return response(404, {"error": str(error)})
    except (ValueError, json.JSONDecodeError) as error:
        return response(400, {"error": str(error)})
    except ClientError as error:
        error_code = error.response.get("Error", {}).get("Code")
        if route_key in {"POST /reservations", "POST /reservations/bulk"} and error_code in {"ConditionalCheckFailedException", "TransactionCanceledException"}:
            return response(409, {"error": "Some of that food is no longer available. Nothing was reserved."})
        if route_key == "POST /reservations/{reservationId}/complete" and error_code == "ConditionalCheckFailedException":
            return response(409, {"error": "This pickup can no longer be completed."})
        if route_key == "POST /me/bootstrap" and error_code in {"ConditionalCheckFailedException", "TransactionCanceledException"}:
            return response(409, {"error": "We could not finish setting up this profile. Please sign out, sign back in, and try again."})
        print(json.dumps({"event": "aws_error", "code": error_code}))
        return response(500, {"error": "A service error occurred."})
    except Exception as error:
        print(json.dumps({"event": "unhandled_error", "type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}))
        return response(500, {"error": "An unexpected error occurred."})
