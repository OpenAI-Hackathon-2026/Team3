import unittest

from pydantic import ValidationError

from models import DonationItem, RecipePlan


class ModelTests(unittest.TestCase):
    def test_donation_quantity_must_be_positive(self):
        with self.assertRaises(ValidationError):
            DonationItem(
                title="Soup",
                description="Prepared soup",
                quantity=0,
                unit="meals",
                category="meal",
                readiness="ready_to_eat",
                confidence=0.9,
            )

    def test_recipe_route_cannot_be_negative(self):
        with self.assertRaises(ValidationError):
            RecipePlan(
                title="Vegetable soup",
                servings=10,
                instructions=["Cook safely"],
                ingredients=[{"listing_id": "one", "name": "Carrots", "quantity": 2, "unit": "lb"}],
                listing_ids=["one"],
                stops=1,
                estimated_route_miles=-1,
            )


if __name__ == "__main__":
    unittest.main()
