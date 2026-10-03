import os
import secrets
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_safe(value):
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    return value


class Repository:
    def __init__(self):
        resource = boto3.resource("dynamodb")
        # Transactions use DynamoDB's low-level AttributeValue format below.
        # Keep this separate from the resource client, which would serialize
        # those values a second time (for example, S -> M) and cancel writes.
        self.client = boto3.client("dynamodb")
        self.users = resource.Table(os.environ["USERS_TABLE"])
        self.organizations = resource.Table(os.environ["ORGANIZATIONS_TABLE"])
        self.memberships = resource.Table(os.environ["MEMBERSHIPS_TABLE"])
        self.listings = resource.Table(os.environ["LISTINGS_TABLE"])
        self.reservations = resource.Table(os.environ["RESERVATIONS_TABLE"])
        self.agent_runs = resource.Table(os.environ["AGENT_RUNS_TABLE"])

    def memberships_for_user(self, user_id: str) -> list[dict]:
        result = self.memberships.query(
            IndexName="UserIndex", KeyConditionExpression=Key("userId").eq(user_id)
        )
        return json_safe(result.get("Items", []))

    def bootstrap_user(self, user_id: str, email: str, display_name: str, account_type: str, organization_name: str | None = None, address: str | None = None, latitude: float | None = None, longitude: float | None = None) -> dict:
        existing = self.users.get_item(Key={"userId": user_id}, ConsistentRead=True).get("Item")
        if existing:
            return {"user": json_safe(existing), "memberships": self.memberships_for_user(user_id)}
        created_at = now_iso()
        user = {"userId": user_id, "email": email, "displayName": display_name, "accountType": account_type, "createdAt": created_at}
        transaction = [{"Put": {"TableName": self.users.name, "Item": {key: self._serialize(value) for key, value in user.items()}, "ConditionExpression": "attribute_not_exists(userId)"}}]
        organization = None
        memberships = []
        if account_type == "donor":
            if not organization_name:
                raise ValueError("A kitchen or organization name is required.")
            organization_id = str(uuid.uuid4())
            organization = {"organizationId": organization_id, "name": organization_name, "type": "donor", "address": address or "", "createdAt": created_at}
            if latitude is not None and longitude is not None:
                organization.update({"latitude": Decimal(str(latitude)), "longitude": Decimal(str(longitude))})
            membership = {"organizationId": organization_id, "userId": user_id, "role": "owner", "createdAt": created_at}
            memberships = [membership]
            transaction.extend([
                {"Put": {"TableName": self.organizations.name, "Item": {key: self._serialize(value) for key, value in organization.items()}, "ConditionExpression": "attribute_not_exists(organizationId)"}},
                {"Put": {"TableName": self.memberships.name, "Item": {key: self._serialize(value) for key, value in membership.items()}, "ConditionExpression": "attribute_not_exists(organizationId) AND attribute_not_exists(userId)"}},
            ])
        self.client.transact_write_items(TransactItems=transaction)
        return {"user": user, "organization": organization, "memberships": memberships}

    def profile(self, user_id: str) -> dict | None:
        item = self.users.get_item(Key={"userId": user_id}).get("Item")
        if not item:
            return None
        return {"user": json_safe(item), "memberships": self.memberships_for_user(user_id)}

    def require_membership(self, user_id: str, organization_id: str, roles: set[str]) -> dict:
        result = self.memberships.get_item(
            Key={"organizationId": organization_id, "userId": user_id},
            ConsistentRead=True,
        ).get("Item")
        if not result or result.get("role") not in roles:
            raise PermissionError("You do not have permission for this organization.")
        return json_safe(result)

    def get_organization(self, organization_id: str) -> dict | None:
        item = self.organizations.get_item(Key={"organizationId": organization_id}).get("Item")
        return json_safe(item) if item else None

    def list_available(self, limit: int = 50) -> list[dict]:
        result = self.listings.query(
            IndexName="StatusPickupIndex",
            KeyConditionExpression=Key("status").eq("available") & Key("pickupEnd").gte(now_iso()),
            Limit=min(limit, 100),
        )
        return json_safe(result.get("Items", []))

    def get_listing(self, listing_id: str) -> dict | None:
        item = self.listings.get_item(Key={"listingId": listing_id}).get("Item")
        return json_safe(item) if item else None

    def recent_donations(self, organization_id: str, limit: int = 10) -> list[dict]:
        result = self.listings.query(
            IndexName="DonorCreatedIndex",
            KeyConditionExpression=Key("organizationId").eq(organization_id),
            ScanIndexForward=False,
            Limit=min(limit, 25),
        )
        return json_safe(result.get("Items", []))

    def create_listing(self, user_id: str, organization_id: str, data: dict) -> dict:
        self.require_membership(user_id, organization_id, {"owner", "manager", "staff"})
        organization = self.get_organization(organization_id) or {}
        created_at = now_iso()
        item = {
            **data,
            "listingId": str(uuid.uuid4()),
            "organizationId": organization_id,
            "organizationName": organization.get("name", "Local kitchen"),
            "pickupAddress": organization.get("address", ""),
            "createdBy": user_id,
            "createdAt": created_at,
            "updatedAt": created_at,
            "status": "available",
            "quantityAvailable": Decimal(str(data["quantityAvailable"])),
        }
        if "latitude" in organization and "longitude" in organization:
            item.update({"latitude": organization["latitude"], "longitude": organization["longitude"]})
        self.listings.put_item(Item=self._ddb_safe(item), ConditionExpression="attribute_not_exists(listingId)")
        return json_safe(item)

    def create_reservation(self, user_id: str, listing_id: str, quantity: float) -> dict:
        listing = self.get_listing(listing_id) or {}
        reservation_id = str(uuid.uuid4())
        created_at = now_iso()
        quantity_decimal = Decimal(str(quantity))
        item = {
            "reservationId": reservation_id,
            "listingId": listing_id,
            "recipientUserId": user_id,
            "quantity": quantity_decimal,
            "status": "reserved",
            "pickupCode": f"{secrets.randbelow(10000):04d}",
            "createdAt": created_at,
        }
        self.client.transact_write_items(
            TransactItems=[
                {
                    "Update": {
                        "TableName": self.listings.name,
                        "Key": {"listingId": {"S": listing_id}},
                        "UpdateExpression": "SET quantityAvailable = quantityAvailable - :q, updatedAt = :now",
                        "ConditionExpression": "#status = :available AND pickupEnd >= :now AND quantityAvailable >= :q",
                        "ExpressionAttributeNames": {"#status": "status"},
                        "ExpressionAttributeValues": {
                            ":q": {"N": str(quantity_decimal)},
                            ":available": {"S": "available"},
                            ":now": {"S": created_at},
                        },
                    }
                },
                {
                    "Put": {
                        "TableName": self.reservations.name,
                        "Item": {key: self._serialize(value) for key, value in item.items()},
                        "ConditionExpression": "attribute_not_exists(reservationId)",
                    }
                },
            ]
        )
        return json_safe({**item, "pickupAddress": listing.get("pickupAddress", ""), "pickupLabel": listing.get("pickupLabel", "")})

    def create_bulk_reservation(self, user_id: str, requested_items: list[dict]) -> dict:
        if not 1 <= len(requested_items) <= 4:
            raise ValueError("A bundle must contain between one and four listings.")
        listing_ids = [str(item.get("listingId", "")) for item in requested_items]
        if len(set(listing_ids)) != len(listing_ids):
            raise ValueError("A bundle cannot contain the same listing twice.")

        bundle_id = str(uuid.uuid4())
        created_at = now_iso()
        reservations = []
        transaction = []
        for requested in requested_items:
            listing_id = str(requested.get("listingId", ""))
            quantity = Decimal(str(requested.get("quantity", 0)))
            if not listing_id or quantity <= 0:
                raise ValueError("Every bundle item requires a listing and positive quantity.")
            listing = self.get_listing(listing_id)
            if not listing:
                raise ValueError("One of the requested listings no longer exists.")
            reservation = {
                "reservationId": str(uuid.uuid4()),
                "bundleId": bundle_id,
                "listingId": listing_id,
                "recipientUserId": user_id,
                "quantity": quantity,
                "status": "reserved",
                "pickupCode": f"{secrets.randbelow(10000):04d}",
                "createdAt": created_at,
            }
            transaction.extend([
                {
                    "Update": {
                        "TableName": self.listings.name,
                        "Key": {"listingId": {"S": listing_id}},
                        "UpdateExpression": "SET quantityAvailable = quantityAvailable - :q, updatedAt = :now",
                        "ConditionExpression": "#status = :available AND pickupEnd >= :now AND quantityAvailable >= :q",
                        "ExpressionAttributeNames": {"#status": "status"},
                        "ExpressionAttributeValues": {
                            ":q": {"N": str(quantity)},
                            ":available": {"S": "available"},
                            ":now": {"S": created_at},
                        },
                    }
                },
                {
                    "Put": {
                        "TableName": self.reservations.name,
                        "Item": {key: self._serialize(value) for key, value in reservation.items()},
                        "ConditionExpression": "attribute_not_exists(reservationId)",
                    }
                },
            ])
            reservations.append(json_safe({
                **reservation,
                "title": listing.get("title", "Ingredient"),
                "pickupAddress": listing.get("pickupAddress", ""),
                "pickupLabel": listing.get("pickupLabel", ""),
            }))

        self.client.transact_write_items(TransactItems=transaction)
        return {"bundleId": bundle_id, "reservations": reservations}

    def reservations_for_user(self, user_id: str, limit: int = 50) -> list[dict]:
        result = self.reservations.query(
            IndexName="RecipientIndex",
            KeyConditionExpression=Key("recipientUserId").eq(user_id),
            ScanIndexForward=False,
            Limit=min(limit, 100),
        )
        return [self._reservation_details(item) for item in result.get("Items", [])]

    def reservations_for_listing(self, user_id: str, listing_id: str, limit: int = 100) -> list[dict]:
        listing = self.get_listing(listing_id)
        if not listing:
            raise LookupError("Listing not found.")
        self.require_membership(user_id, listing["organizationId"], {"owner", "manager", "staff"})
        result = self.reservations.query(
            IndexName="ListingIndex",
            KeyConditionExpression=Key("listingId").eq(listing_id),
            ScanIndexForward=False,
            Limit=min(limit, 100),
        )
        return [self._reservation_details(item, listing=listing, include_recipient=True) for item in result.get("Items", [])]

    def complete_reservation(self, user_id: str, reservation_id: str) -> dict:
        reservation = self.reservations.get_item(
            Key={"reservationId": reservation_id}, ConsistentRead=True
        ).get("Item")
        if not reservation:
            raise LookupError("Reservation not found.")
        listing = self.get_listing(str(reservation["listingId"]))
        if not listing:
            raise LookupError("Listing not found.")
        self.require_membership(user_id, listing["organizationId"], {"owner", "manager", "staff"})
        if reservation.get("status") == "completed":
            return self._reservation_details(reservation, listing=listing, include_recipient=True)
        completed_at = now_iso()
        result = self.reservations.update_item(
            Key={"reservationId": reservation_id},
            UpdateExpression="SET #status = :completed, completedAt = :completed_at, completedBy = :completed_by",
            ConditionExpression="#status = :reserved",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":reserved": "reserved",
                ":completed": "completed",
                ":completed_at": completed_at,
                ":completed_by": user_id,
            },
            ReturnValues="ALL_NEW",
        )
        return self._reservation_details(result["Attributes"], listing=listing, include_recipient=True)

    def _reservation_details(self, reservation: dict, *, listing: dict | None = None, include_recipient: bool = False) -> dict:
        safe_reservation = json_safe(reservation)
        listing = listing or self.get_listing(str(safe_reservation["listingId"])) or {}
        details = {
            **safe_reservation,
            "title": listing.get("title", "Food pickup"),
            "unit": listing.get("unit", "items"),
            "organizationName": listing.get("organizationName", "Local kitchen"),
            "pickupAddress": listing.get("pickupAddress", ""),
            "pickupLabel": listing.get("pickupLabel", ""),
        }
        if include_recipient:
            recipient = self.users.get_item(
                Key={"userId": safe_reservation["recipientUserId"]}
            ).get("Item") or {}
            details["recipientName"] = recipient.get("displayName", "Food seeker")
        details.pop("recipientUserId", None)
        details.pop("completedBy", None)
        return json_safe(details)

    def save_agent_draft(self, user_id: str, organization_id: str, kind: str, payload: dict) -> dict:
        self.require_membership(user_id, organization_id, {"owner", "manager", "staff"})
        created_at = now_iso()
        item = {
            "runId": str(uuid.uuid4()),
            "organizationId": organization_id,
            "userId": user_id,
            "kind": kind,
            "status": "draft",
            "payload": payload,
            "createdAt": created_at,
            "expiresAt": int(time.time()) + 60 * 60 * 24 * 14,
        }
        self.agent_runs.put_item(Item=self._ddb_safe(item))
        return json_safe(item)

    def create_recipe_job(self, user_id: str, *, max_stops: int, max_miles: float) -> dict:
        created_at = now_iso()
        item = {
            "runId": str(uuid.uuid4()),
            "userId": user_id,
            "userRecipeId": user_id,
            "kind": "recipe-planning",
            "status": "queued",
            "maxStops": max_stops,
            "maxMiles": Decimal(str(max_miles)),
            "createdAt": created_at,
            "updatedAt": created_at,
            "expiresAt": int(time.time()) + 60 * 60 * 24 * 14,
        }
        self.agent_runs.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(runId)",
        )
        return self._public_recipe_job(item)

    def get_recipe_job(self, user_id: str, run_id: str) -> dict | None:
        item = self.agent_runs.get_item(
            Key={"runId": run_id}, ConsistentRead=True
        ).get("Item")
        if not item or item.get("kind") != "recipe-planning" or item.get("userId") != user_id:
            return None
        return self._public_recipe_job(item)

    def recipe_jobs_for_user(self, user_id: str, limit: int = 10) -> list[dict]:
        result = self.agent_runs.query(
            IndexName="RecipeUserCreatedIndex",
            KeyConditionExpression=Key("userRecipeId").eq(user_id),
            ScanIndexForward=False,
            Limit=min(limit, 25),
        )
        return [self._public_recipe_job(item) for item in result.get("Items", [])]

    def start_recipe_job(self, run_id: str) -> bool:
        job = self.agent_runs.get_item(
            Key={"runId": run_id}, ConsistentRead=True
        ).get("Item")
        if not job or job.get("kind") != "recipe-planning" or job.get("status") in {"succeeded", "failed"}:
            return False
        try:
            self.agent_runs.update_item(
                Key={"runId": run_id},
                UpdateExpression="SET #status = :running, updatedAt = :updated_at REMOVE #error",
                ConditionExpression="#status IN (:queued, :running)",
                ExpressionAttributeNames={"#status": "status", "#error": "error"},
                ExpressionAttributeValues={
                    ":queued": "queued",
                    ":running": "running",
                    ":updated_at": now_iso(),
                },
            )
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def complete_recipe_job(self, run_id: str, result: dict) -> None:
        self.agent_runs.update_item(
            Key={"runId": run_id},
            UpdateExpression="SET #status = :succeeded, #result = :result, updatedAt = :updated_at REMOVE #error",
            ExpressionAttributeNames={"#status": "status", "#result": "result", "#error": "error"},
            ExpressionAttributeValues={
                ":succeeded": "succeeded",
                ":result": self._ddb_safe(result),
                ":updated_at": now_iso(),
            },
        )

    def fail_recipe_job(self, run_id: str, message: str) -> None:
        self.agent_runs.update_item(
            Key={"runId": run_id},
            UpdateExpression="SET #status = :failed, #error = :error, updatedAt = :updated_at REMOVE #result",
            ExpressionAttributeNames={"#status": "status", "#error": "error", "#result": "result"},
            ExpressionAttributeValues={
                ":failed": "failed",
                ":error": message[:500],
                ":updated_at": now_iso(),
            },
        )

    @staticmethod
    def _public_recipe_job(item: dict) -> dict:
        safe = json_safe(item)
        return {
            key: safe[key]
            for key in (
                "runId",
                "status",
                "maxStops",
                "maxMiles",
                "createdAt",
                "updatedAt",
                "result",
                "error",
            )
            if key in safe
        }

    @staticmethod
    def _ddb_safe(value):
        if isinstance(value, float):
            return Decimal(str(value))
        if isinstance(value, list):
            return [Repository._ddb_safe(item) for item in value]
        if isinstance(value, dict):
            return {key: Repository._ddb_safe(item) for key, item in value.items()}
        return value

    @staticmethod
    def _serialize(value):
        from boto3.dynamodb.types import TypeSerializer

        return TypeSerializer().serialize(value)
