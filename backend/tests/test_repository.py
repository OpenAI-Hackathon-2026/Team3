import unittest
from decimal import Decimal
from types import SimpleNamespace

from repository import Repository


class RepositorySerializationTests(unittest.TestCase):
    def test_transaction_values_use_low_level_attribute_format(self):
        self.assertEqual(Repository._serialize("user-123"), {"S": "user-123"})
        self.assertEqual(Repository._serialize(Decimal("2.5")), {"N": "2.5"})

    def test_bulk_reservation_uses_one_transaction_for_every_listing(self):
        repository = Repository.__new__(Repository)
        repository.listings = SimpleNamespace(name="Listings")
        repository.reservations = SimpleNamespace(name="Reservations")
        calls = []
        repository.client = SimpleNamespace(transact_write_items=lambda **kwargs: calls.append(kwargs))
        repository.get_listing = lambda listing_id: {
            "listingId": listing_id,
            "title": f"Ingredient {listing_id}",
            "status": "available",
            "pickupAddress": "Private until reserved",
            "pickupLabel": "8–9 PM",
        }

        result = repository.create_bulk_reservation("recipient-1", [
            {"listingId": "one", "quantity": 2},
            {"listingId": "two", "quantity": 3},
        ])

        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0]["TransactItems"]), 4)
        self.assertEqual(len(result["reservations"]), 2)
        self.assertEqual(result["reservations"][0]["bundleId"], result["reservations"][1]["bundleId"])

    def test_ddb_safe_preserves_decimals_and_converts_nested_floats(self):
        value = {
            "quantityAvailable": Decimal("12"),
            "coordinates": [35.2271, -80.8431],
        }

        self.assertEqual(
            Repository._ddb_safe(value),
            {
                "quantityAvailable": Decimal("12"),
                "coordinates": [Decimal("35.2271"), Decimal("-80.8431")],
            },
        )

    def test_listing_reservations_require_membership_and_include_recipient_name(self):
        repository = Repository.__new__(Repository)
        repository.get_listing = lambda listing_id: {
            "listingId": listing_id,
            "organizationId": "kitchen-1",
            "title": "Dinner boxes",
            "organizationName": "Good Kitchen",
            "pickupAddress": "123 Main St",
            "pickupLabel": "6–7 PM",
        }
        checked = []
        repository.require_membership = lambda user_id, organization_id, roles: checked.append((user_id, organization_id, roles))
        repository.reservations = SimpleNamespace(query=lambda **kwargs: {"Items": [{
            "reservationId": "reservation-1",
            "listingId": "listing-1",
            "recipientUserId": "recipient-1",
            "quantity": Decimal("2"),
            "status": "reserved",
            "pickupCode": "1234",
            "createdAt": "2026-10-03T12:00:00+00:00",
        }]})
        repository.users = SimpleNamespace(get_item=lambda **kwargs: {"Item": {"displayName": "Sam"}})

        result = repository.reservations_for_listing("staff-1", "listing-1")

        self.assertEqual(checked[0][0:2], ("staff-1", "kitchen-1"))
        self.assertEqual(result[0]["recipientName"], "Sam")
        self.assertEqual(result[0]["title"], "Dinner boxes")

    def test_recipient_reservations_include_pickup_details(self):
        repository = Repository.__new__(Repository)
        repository.reservations = SimpleNamespace(query=lambda **kwargs: {"Items": [{
            "reservationId": "reservation-1",
            "listingId": "listing-1",
            "recipientUserId": "recipient-1",
            "quantity": Decimal("1"),
            "status": "reserved",
            "pickupCode": "9876",
            "createdAt": "2026-10-03T12:00:00+00:00",
        }]})
        repository.get_listing = lambda listing_id: {
            "title": "Soup",
            "organizationName": "Neighborhood Kitchen",
            "pickupAddress": "10 Oak Ave",
            "pickupLabel": "7–8 PM",
        }

        result = repository.reservations_for_user("recipient-1")

        self.assertEqual(result[0]["pickupAddress"], "10 Oak Ave")
        self.assertEqual(result[0]["organizationName"], "Neighborhood Kitchen")

    def test_complete_reservation_records_completion(self):
        repository = Repository.__new__(Repository)
        repository.reservations = SimpleNamespace(
            get_item=lambda **kwargs: {"Item": {
                "reservationId": "reservation-1",
                "listingId": "listing-1",
                "recipientUserId": "recipient-1",
                "quantity": Decimal("2"),
                "status": "reserved",
                "pickupCode": "1234",
            }},
            update_item=lambda **kwargs: {"Attributes": {
                "reservationId": "reservation-1",
                "listingId": "listing-1",
                "recipientUserId": "recipient-1",
                "quantity": Decimal("2"),
                "status": "completed",
                "pickupCode": "1234",
                "completedBy": "staff-1",
            }},
        )
        repository.get_listing = lambda listing_id: {
            "organizationId": "kitchen-1", "title": "Dinner boxes"
        }
        repository.require_membership = lambda *args: None
        repository.users = SimpleNamespace(get_item=lambda **kwargs: {"Item": {"displayName": "Sam"}})

        result = repository.complete_reservation("staff-1", "reservation-1")

        self.assertEqual(result["status"], "completed")
        self.assertNotIn("completedBy", result)

    def test_recipe_job_is_persisted_without_location(self):
        written = []
        repository = Repository.__new__(Repository)
        repository.agent_runs = SimpleNamespace(put_item=lambda **kwargs: written.append(kwargs))

        result = repository.create_recipe_job("recipient-1", max_stops=2, max_miles=3.5)

        item = written[0]["Item"]
        self.assertEqual(result["status"], "queued")
        self.assertEqual(item["userRecipeId"], "recipient-1")
        self.assertNotIn("latitude", item)
        self.assertNotIn("longitude", item)

    def test_recipe_job_lookup_is_scoped_to_its_user(self):
        repository = Repository.__new__(Repository)
        repository.agent_runs = SimpleNamespace(get_item=lambda **kwargs: {"Item": {
            "runId": "run-1",
            "userId": "recipient-1",
            "kind": "recipe-planning",
            "status": "succeeded",
            "result": {"plans": [], "explanation": "Nothing nearby."},
            "createdAt": "2026-10-03T12:00:00+00:00",
            "updatedAt": "2026-10-03T12:01:00+00:00",
        }})

        self.assertIsNone(repository.get_recipe_job("recipient-2", "run-1"))
        self.assertEqual(repository.get_recipe_job("recipient-1", "run-1")["status"], "succeeded")


if __name__ == "__main__":
    unittest.main()
