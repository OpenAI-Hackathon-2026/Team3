import unittest
from datetime import datetime, timezone

from seed_demo import KITCHENS, build_records, stable_id


class DemoSeedTests(unittest.TestCase):
    def test_seed_has_six_kitchens_and_thirty_published_ingredients(self):
        records = build_records(datetime(2026, 10, 3, 12, tzinfo=timezone.utc))

        self.assertEqual(len(records["users"]), 6)
        self.assertEqual(len(records["organizations"]), 6)
        self.assertEqual(len(records["memberships"]), 6)
        self.assertEqual(len(records["listings"]), 30)
        self.assertTrue(all(item["status"] == "available" for item in records["listings"]))
        self.assertTrue(all(item["category"] == "ingredient" for item in records["listings"]))

    def test_every_kitchen_is_in_south_end_and_has_unique_ids(self):
        records = build_records(datetime(2026, 10, 3, 12, tzinfo=timezone.utc))

        self.assertTrue(all(org["neighborhood"] == "South End, Charlotte" for org in records["organizations"]))
        self.assertEqual(len({item["listingId"] for item in records["listings"]}), len(records["listings"]))
        self.assertEqual(len({kitchen["slug"] for kitchen in KITCHENS}), 6)

    def test_ids_are_stable(self):
        self.assertEqual(stable_id("user", "superica"), stable_id("user", "superica"))
        self.assertNotEqual(stable_id("user", "superica"), stable_id("organization", "superica"))

    def test_pickup_window_matches_the_evening_label(self):
        records = build_records(datetime(2026, 10, 3, 12, tzinfo=timezone.utc))
        listing = records["listings"][0]

        self.assertEqual(listing["pickupStart"], "2026-10-04T22:00:00+00:00")
        self.assertEqual(listing["pickupEnd"], "2026-10-05T02:00:00+00:00")
        self.assertEqual(listing["pickupLabel"], "Tomorrow, 6–10 PM")


if __name__ == "__main__":
    unittest.main()
