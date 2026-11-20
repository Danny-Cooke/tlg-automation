"""Print the school's private course-dates link (plan job 21). The page has no
login: the long key after #key= is what opens it, so the link is for the
owners only. Run it on the laptop with AWS credentials:

    python scripts/academy_admin_link.py
    python scripts/academy_admin_link.py --new     # make a new key; the old link stops working within five minutes

The key lives in the Secrets Manager secret <prefix>/academy/stripe
(admin_key), created by scripts/academy_stripe_setup.py on the first deploy.
"""
from __future__ import annotations

import argparse
import json
import secrets

import boto3

PAGE = "https://tlg-beauty.co.uk/academy/course-dates/"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--secret", default="tlg-prod/academy/stripe")
    ap.add_argument("--region", default="eu-west-2")
    ap.add_argument("--page", default=PAGE)
    ap.add_argument("--new", action="store_true", help="replace the key; every copy of the old link stops working")
    args = ap.parse_args()
    sm = boto3.client("secretsmanager", region_name=args.region)
    try:
        held = json.loads(sm.get_secret_value(SecretId=args.secret)["SecretString"] or "{}")
    except (sm.exceptions.ResourceNotFoundException, KeyError):
        print("The shop's secret has no value yet: run the Academy workflow once, then try again.")
        return 1
    if args.new or not held.get("admin_key"):
        held["admin_key"] = secrets.token_urlsafe(32)
        sm.put_secret_value(SecretId=args.secret, SecretString=json.dumps(held))
        print("New key made. The old link stops working within five minutes.")
    print(f"{args.page}#key={held['admin_key']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
