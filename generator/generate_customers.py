"""Meridian synthetic customer book generator.

Emits the same underlying population through THREE simulated source systems,
each with its own realistic corruption profile, plus a ground-truth mapping
for evaluating entity resolution precision/recall.

Deterministic: same --seed => byte-identical output. Every test and game-day
depends on that property; do not introduce nondeterminism here.

Outputs (CSV) under data/bronze/customers/:
  crm_customers.csv        — clean-ish, nicknames, title-case
  loans_customers.csv      — UPPERCASE, "LAST, FIRST", MM/DD/YYYY dobs, typos
  legacy_customers.csv     — truncated fields, missing dobs, sentinel values,
                             occasional duplicate rows
  _truth.csv               — customer_id -> record ids across systems

Usage:
  python generator/generate_customers.py --count 5000 --seed 42
"""
from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

FIRST_NAMES = [
    "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael",
    "Linda", "William", "Elizabeth", "David", "Barbara", "Richard", "Susan",
    "Joseph", "Jessica", "Thomas", "Sarah", "Charles", "Karen", "Christopher",
    "Nancy", "Daniel", "Lisa", "Matthew", "Betty", "Anthony", "Margaret",
    "Mark", "Sandra", "Aisha", "Wei", "Carlos", "Priya", "Mohammed", "Olga",
]
NICKNAMES = {
    "James": "Jim", "John": "Jon", "Robert": "Bob", "Michael": "Mike",
    "William": "Bill", "Elizabeth": "Liz", "Richard": "Rick", "Joseph": "Joe",
    "Thomas": "Tom", "Charles": "Chuck", "Christopher": "Chris",
    "Daniel": "Dan", "Matthew": "Matt", "Margaret": "Peggy", "Jennifer": "Jen",
}
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Nguyen", "Patel", "Khan", "Chen",
]
STREET_NAMES = [
    "Oak", "Maple", "Cedar", "Pine", "Elm", "Washington", "Lake", "Hill",
    "Sunset", "Ridge", "Park", "Main", "Church", "River", "Highland",
]
STREET_TYPES = ["St", "Ave", "Rd", "Ln", "Dr", "Blvd", "Ct"]
STREET_TYPE_LONG = {
    "St": "Street", "Ave": "Avenue", "Rd": "Road", "Ln": "Lane",
    "Dr": "Drive", "Blvd": "Boulevard", "Ct": "Court",
}
CITIES = [
    ("Springfield", "IL", "627"), ("Riverton", "NJ", "080"),
    ("Fairview", "TX", "750"), ("Georgetown", "KY", "403"),
    ("Clinton", "MS", "390"), ("Madison", "WI", "537"),
    ("Franklin", "TN", "370"), ("Greenville", "SC", "296"),
]


def _typo(rng: random.Random, s: str) -> str:
    """Introduce one keyboard-adjacent-ish typo (swap, drop, or double)."""
    if len(s) < 4:
        return s
    i = rng.randrange(1, len(s) - 1)
    op = rng.choice(["swap", "drop", "double"])
    if op == "swap":
        return s[: i - 1] + s[i] + s[i - 1] + s[i + 1 :]
    if op == "drop":
        return s[:i] + s[i + 1 :]
    return s[:i] + s[i] + s[i:]


def _make_base(rng: random.Random, n: int) -> list[dict]:
    people = []
    for i in range(n):
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        dob_y = rng.randint(1940, 2004)
        dob_m = rng.randint(1, 12)
        dob_d = rng.randint(1, 28)
        num = rng.randint(1, 9999)
        street = rng.choice(STREET_NAMES)
        stype = rng.choice(STREET_TYPES)
        city, state, zip3 = rng.choice(CITIES)
        people.append(
            {
                "customer_id": f"CUST{i:07d}",
                "first": first,
                "last": last,
                "dob": f"{dob_y:04d}-{dob_m:02d}-{dob_d:02d}",
                "street_num": num,
                "street": street,
                "stype": stype,
                "city": city,
                "state": state,
                "zip": f"{zip3}{rng.randint(0,99):02d}",
                "ssn4": f"{rng.randint(0,9999):04d}",
            }
        )
    return people


def _crm_row(rng: random.Random, p: dict, rid: int) -> dict:
    first = p["first"]
    if first in NICKNAMES and rng.random() < 0.30:
        first = NICKNAMES[first]
    return {
        "crm_id": f"CRM-{rid:08d}",
        "full_name": f"{first} {p['last']}",
        "dob": p["dob"],
        "address": f"{p['street_num']} {p['street']} {p['stype']}",
        "city": p["city"],
        "state": p["state"],
        "zip": p["zip"],
        "email": f"{first.lower()}.{p['last'].lower()}{rng.randint(1,99)}@example.com",
    }


def _loans_row(rng: random.Random, p: dict, rid: int) -> dict:
    last = p["last"].upper()
    first = p["first"].upper()
    if rng.random() < 0.08:
        last = _typo(rng, last)
    y, m, d = p["dob"].split("-")
    stype = STREET_TYPE_LONG[p["stype"]].upper()
    return {
        "loan_cust_id": f"LN{rid:09d}",
        "name": f"{last}, {first}",
        "date_of_birth": f"{m}/{d}/{y}",
        "addr_line1": f"{p['street_num']} {p['street'].upper()} {stype}",
        "addr_city": p["city"].upper(),
        "addr_state": p["state"],
        "addr_zip": p["zip"],
        "ssn_last4": p["ssn4"],
    }


def _legacy_row(rng: random.Random, p: dict, rid: int) -> dict:
    dob = p["dob"]
    r = rng.random()
    if r < 0.15:
        dob = ""  # missing
    elif r < 0.20:
        dob = "1900-01-01"  # sentinel meaning "unknown"
    first = p["first"][:1] if rng.random() < 0.25 else p["first"]
    return {
        "cust_no": f"{rid:06d}",
        "fname": first[:10],
        "lname": p["last"][:12],
        "birth_dt": dob,
        "street": f"{p['street'].lower()} {p['stype'].lower()} {p['street_num']}",
        "city": p["city"][:10],
        "st": p["state"],
        "zip5": p["zip"] if rng.random() > 0.10 else "00000",
    }


def generate(count: int, seed: int, out_dir: Path) -> dict:
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = _make_base(rng, count)

    crm_rows, loan_rows, legacy_rows, truth = [], [], [], []
    for idx, p in enumerate(base):
        in_crm = rng.random() < 0.90
        in_loans = rng.random() < 0.75
        in_legacy = rng.random() < 0.55
        t = {"customer_id": p["customer_id"], "crm_id": "", "loan_cust_id": "", "cust_no": ""}
        if in_crm:
            row = _crm_row(rng, p, idx)
            crm_rows.append(row)
            t["crm_id"] = row["crm_id"]
        if in_loans:
            row = _loans_row(rng, p, idx)
            loan_rows.append(row)
            t["loan_cust_id"] = row["loan_cust_id"]
        if in_legacy:
            row = _legacy_row(rng, p, idx)
            legacy_rows.append(row)
            t["cust_no"] = row["cust_no"]
            if rng.random() < 0.03:  # legacy occasionally duplicates rows
                legacy_rows.append(dict(row))
        truth.append(t)

    def _write(name: str, rows: list[dict]) -> None:
        if not rows:
            return
        with (out_dir / name).open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    _write("crm_customers.csv", crm_rows)
    _write("loans_customers.csv", loan_rows)
    _write("legacy_customers.csv", legacy_rows)
    _write("_truth.csv", truth)

    return {
        "base_population": count,
        "crm": len(crm_rows),
        "loans": len(loan_rows),
        "legacy": len(legacy_rows),
        "out_dir": str(out_dir),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=Path("data/bronze/customers"))
    args = ap.parse_args()
    print(generate(args.count, args.seed, args.out))
