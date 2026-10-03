"""Seed the deployed development tables with a South End meal-planner demo.

The IDs are deterministic, so running this script again refreshes quantities and
pickup windows instead of creating duplicate kitchens or listings. Records that
were not created by this script are never scanned, changed, or deleted.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from boto3.dynamodb.types import TypeSerializer


SEED_NAMESPACE = uuid.UUID("d58e9f68-5565-4e5d-9de4-92f7454dca8d")


KITCHENS = [
    {
        "slug": "club-west-brewing",
        "name": "Club West Brewing",
        "manager": "Jordan Ellis",
        "address": "2151 Hawkins St, Charlotte, NC 28203",
        "latitude": 35.20899,
        "longitude": -80.86199,
        "ingredients": [
            ("Citrus-herb grilled chicken", "Fully cooked chicken, chilled after service; useful for tacos, grain bowls, or salads.", 18, "lb", "ready_to_eat", []),
            ("Roasted sweet potatoes", "Roasted sweet potato wedges with neutral seasoning.", 16, "lb", "ready_to_eat", []),
            ("Shredded green cabbage", "Fresh shredded cabbage for slaw, tacos, or stir-fries.", 12, "lb", "needs_cooking", []),
            ("House-pickled red onions", "Bright pickled onions packed cold for toppings and salads.", 8, "lb", "ready_to_eat", []),
            ("Pretzel rolls", "Soft pretzel sandwich rolls from today’s service.", 36, "items", "ready_to_eat", ["wheat"]),
        ],
    },
    {
        "slug": "chapter-6",
        "name": "Chapter 6",
        "manager": "Samira Haddad",
        "address": "2151 Hawkins St, Charlotte, NC 28203",
        "latitude": 35.20899,
        "longitude": -80.86199,
        "ingredients": [
            ("Cooked pearl couscous", "Chilled pearl couscous ready for Mediterranean bowls or warm pilaf.", 14, "lb", "ready_to_eat", ["wheat"]),
            ("Lemon-herb chickpeas", "Cooked chickpeas tossed with lemon and herbs.", 16, "lb", "ready_to_eat", []),
            ("Roasted eggplant", "Tender roasted eggplant with olive oil and light seasoning.", 12, "lb", "ready_to_eat", []),
            ("Charred zucchini", "Charred zucchini pieces suited to bowls, pasta, or frittatas.", 10, "lb", "ready_to_eat", []),
            ("Fresh parsley and mint", "Washed mixed herbs for salads, sauces, and garnishes.", 4, "lb", "ready_to_eat", []),
        ],
    },
    {
        "slug": "tremont-kitchen-bar",
        "name": "Tremont Kitchen + Bar",
        "manager": "Casey Morgan",
        "address": "2000 South Blvd, Suite 530, Charlotte, NC 28203",
        "latitude": 35.20927,
        "longitude": -80.86068,
        "ingredients": [
            ("Grilled chicken breasts", "Fully cooked grilled chicken breasts, chilled and ready to slice.", 16, "lb", "ready_to_eat", []),
            ("Brioche buns", "Soft brioche sandwich buns from today’s service.", 32, "items", "ready_to_eat", ["wheat", "milk", "eggs"]),
            ("Sliced tomatoes", "Fresh sliced tomatoes kept refrigerated.", 10, "lb", "ready_to_eat", []),
            ("Sautéed mushrooms", "Cooked mushrooms with light seasoning for sandwiches, bowls, or pasta.", 10, "lb", "ready_to_eat", []),
            ("Mixed salad greens", "Washed mixed greens ready for salads or sandwich toppings.", 12, "lb", "ready_to_eat", []),
        ],
    },
    {
        "slug": "superica",
        "name": "Superica",
        "manager": "Marisol Vega",
        "address": "101 W Worthington Ave, Suite 100, Charlotte, NC 28203",
        "latitude": 35.21151,
        "longitude": -80.86026,
        "ingredients": [
            ("Flour tortillas", "Fresh flour tortillas for tacos, wraps, or baked tortilla chips.", 48, "items", "ready_to_eat", ["wheat"]),
            ("Seasoned black beans", "Fully cooked black beans with mild seasoning.", 18, "lb", "ready_to_eat", []),
            ("Roasted corn", "Roasted corn kernels for tacos, bowls, soups, or salads.", 14, "lb", "ready_to_eat", []),
            ("Fajita peppers and onions", "Cooked strips of bell pepper and onion.", 12, "lb", "ready_to_eat", []),
            ("Salsa roja", "House red salsa packed cold; medium heat.", 8, "lb", "ready_to_eat", []),
        ],
    },
    {
        "slug": "hawkers",
        "name": "Hawkers Asian Street Food",
        "manager": "Alex Nguyen",
        "address": "1930 Camden Rd, Suite 260, Charlotte, NC 28203",
        "latitude": 35.21108,
        "longitude": -80.86102,
        "ingredients": [
            ("Cooked jasmine rice", "Chilled cooked jasmine rice; reheat thoroughly for bowls or fried rice.", 20, "lb", "needs_cooking", []),
            ("Wok-ready bok choy", "Washed bok choy ready for a quick sauté or stir-fry.", 14, "lb", "needs_cooking", []),
            ("Sliced shiitake mushrooms", "Fresh sliced shiitakes for stir-fries, soup, or rice bowls.", 10, "lb", "needs_cooking", []),
            ("Marinated tofu", "Chilled tofu in a light savory marinade, ready to cook.", 12, "lb", "needs_cooking", ["soy"]),
            ("Fresh scallions", "Washed scallions for fried rice, noodles, and garnishes.", 5, "lb", "ready_to_eat", []),
        ],
    },
    {
        "slug": "barcelona-wine-bar",
        "name": "Barcelona Wine Bar",
        "manager": "Elena Ruiz",
        "address": "101 W Worthington Ave, Suite 110, Charlotte, NC 28203",
        "latitude": 35.21151,
        "longitude": -80.86026,
        "ingredients": [
            ("Roasted piquillo peppers", "Sweet roasted peppers packed cold for tapas, bowls, or sandwiches.", 10, "lb", "ready_to_eat", []),
            ("Par-cooked potatoes", "Par-cooked potatoes ready to roast, crisp, or add to a tortilla española.", 18, "lb", "needs_cooking", []),
            ("Spanish chorizo", "Sliced cured pork chorizo for stews, rice dishes, or tapas.", 12, "lb", "ready_to_eat", []),
            ("Marinated white beans", "Cooked white beans with olive oil and mild herbs.", 14, "lb", "ready_to_eat", []),
            ("Chopped kale", "Washed chopped kale for soups, sautés, or grain bowls.", 10, "lb", "needs_cooking", []),
        ],
    },
]


def stable_id(kind: str, slug: str) -> str:
    return str(uuid.uuid5(SEED_NAMESPACE, f"{kind}:{slug}"))


def aws_json(region: str, *args: str) -> dict:
    result = subprocess.run(
        ["aws", *args, "--region", region, "--output", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def stack_tables(stack_name: str, region: str) -> dict[str, str]:
    resources = aws_json(region, "cloudformation", "list-stack-resources", "--stack-name", stack_name)[
        "StackResourceSummaries"
    ]
    names = {
        item["LogicalResourceId"]: item["PhysicalResourceId"]
        for item in resources
        if item["LogicalResourceId"] in {"UsersTable", "OrganizationsTable", "MembershipsTable", "ListingsTable"}
    }
    missing = {"UsersTable", "OrganizationsTable", "MembershipsTable", "ListingsTable"} - names.keys()
    if missing:
        raise RuntimeError(f"Stack is missing required tables: {', '.join(sorted(missing))}")
    return names


def write_records(table_name: str, records: list[dict], region: str) -> None:
    serializer = TypeSerializer()
    pending = [
        {"PutRequest": {"Item": {key: serializer.serialize(value) for key, value in item.items()}}}
        for item in records
    ]
    while pending:
        batch, pending = pending[:25], pending[25:]
        request = {table_name: batch}
        for attempt in range(6):
            response = aws_json(
                region,
                "dynamodb",
                "batch-write-item",
                "--request-items",
                json.dumps(request, separators=(",", ":")),
            )
            unprocessed = response.get("UnprocessedItems", {}).get(table_name, [])
            if not unprocessed:
                break
            request = {table_name: unprocessed}
            time.sleep(0.25 * (2**attempt))
        else:
            raise RuntimeError(f"DynamoDB did not process {len(unprocessed)} records for {table_name}")


def build_records(now: datetime) -> dict[str, list[dict]]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    created_at = now.astimezone(timezone.utc).isoformat()
    charlotte_now = now.astimezone(ZoneInfo("America/New_York"))
    pickup_start_local = charlotte_now.replace(hour=18, minute=0, second=0, microsecond=0) + timedelta(days=1)
    pickup_end_local = pickup_start_local.replace(hour=22)
    pickup_start = pickup_start_local.astimezone(timezone.utc).isoformat()
    pickup_end = pickup_end_local.astimezone(timezone.utc).isoformat()
    pickup_label = "Tomorrow, 6–10 PM"
    records: dict[str, list[dict]] = {"users": [], "organizations": [], "memberships": [], "listings": []}

    for kitchen in KITCHENS:
        slug = kitchen["slug"]
        user_id = stable_id("user", slug)
        organization_id = stable_id("organization", slug)
        records["users"].append({
            "userId": user_id,
            "email": f"kitchen+{slug}@secondserving.demo",
            "displayName": kitchen["manager"],
            "accountType": "donor",
            "createdAt": created_at,
            "seedKey": "south-end-demo-v1",
        })
        records["organizations"].append({
            "organizationId": organization_id,
            "name": kitchen["name"],
            "type": "donor",
            "address": kitchen["address"],
            "neighborhood": "South End, Charlotte",
            "latitude": Decimal(str(kitchen["latitude"])),
            "longitude": Decimal(str(kitchen["longitude"])),
            "createdAt": created_at,
            "seedKey": "south-end-demo-v1",
        })
        records["memberships"].append({
            "organizationId": organization_id,
            "userId": user_id,
            "role": "owner",
            "createdAt": created_at,
            "seedKey": "south-end-demo-v1",
        })
        for index, ingredient in enumerate(kitchen["ingredients"]):
            title, description, quantity, unit, readiness, allergens = ingredient
            ingredient_slug = title.lower().replace(" ", "-")
            listing_id = stable_id("listing", f"{slug}:{ingredient_slug}")
            records["listings"].append({
                "listingId": listing_id,
                "organizationId": organization_id,
                "organizationName": kitchen["name"],
                "pickupAddress": kitchen["address"],
                "latitude": Decimal(str(kitchen["latitude"])),
                "longitude": Decimal(str(kitchen["longitude"])),
                "createdBy": user_id,
                "createdAt": (now + timedelta(microseconds=index)).astimezone(timezone.utc).isoformat(),
                "updatedAt": created_at,
                "status": "available",
                "title": title,
                "description": description,
                "quantityAvailable": Decimal(str(quantity)),
                "unit": unit,
                "category": "ingredient",
                "readiness": readiness,
                "allergens": allergens,
                "storage": "Keep refrigerated at 41°F or below.",
                "pickupStart": pickup_start,
                "pickupEnd": pickup_end,
                "pickupLabel": pickup_label,
                "seedKey": "south-end-demo-v1",
            })
    return records


def seed(stack_name: str, region: str, dry_run: bool = False) -> dict[str, int]:
    table_names = stack_tables(stack_name, region)
    records = build_records(datetime.now(timezone.utc))
    counts = {kind: len(items) for kind, items in records.items()}
    if dry_run:
        return counts

    destinations = {
        "users": "UsersTable",
        "organizations": "OrganizationsTable",
        "memberships": "MembershipsTable",
        "listings": "ListingsTable",
    }
    for kind, logical_name in destinations.items():
        write_records(table_names[logical_name], records[kind], region)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack-name", default="second-serving-dev")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    counts = seed(args.stack_name, args.region, args.dry_run)
    action = "Would seed" if args.dry_run else "Seeded"
    print(
        f"{action} {counts['users']} kitchen users, {counts['organizations']} organizations, "
        f"{counts['memberships']} memberships, and {counts['listings']} published ingredients."
    )


if __name__ == "__main__":
    main()
