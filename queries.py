import math

import psycopg
from psycopg.rows import dict_row


def validate_limit(limit):
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")


def search_name(name, limit=100):
    """Case-insensitive exact name search."""
    validate_limit(limit)

    with psycopg.connect("", row_factory=dict_row) as conn:
        return conn.execute(
            """
            SELECT id, name, ra_deg, dec_deg
            FROM sources
            WHERE lower(name) = lower(%s)
            ORDER BY id
            LIMIT %s
            """,
            (name, limit),
        ).fetchall()


def cone_search(ra, dec, radius, limit=100):
    """Coordinates and radius are in decimal degrees."""
    validate_limit(limit)

    if not all(math.isfinite(v) for v in (ra, dec, radius)):
        raise ValueError("Coordinates and radius must be finite")
    if not 0 <= ra < 360:
        raise ValueError("RA must be in [0, 360)")
    if not -90 <= dec <= 90:
        raise ValueError("Dec must be in [-90, 90]")
    if not 0 < radius <= 180:
        raise ValueError("Radius must be in (0, 180]")

    with psycopg.connect("", row_factory=dict_row) as conn:
        return conn.execute(
            """
            SELECT
                id, name, ra_deg, dec_deg,
                degrees(
                    position <-> spoint(radians(%s), radians(%s))
                ) AS separation_deg
            FROM sources
            WHERE position <@ scircle(
                spoint(radians(%s), radians(%s)),
                radians(%s)
            )
            ORDER BY separation_deg, id
            LIMIT %s
            """,
            (ra, dec, ra, dec, radius, limit),
        ).fetchall()


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    names = commands.add_parser("name")
    names.add_argument("name")
    names.add_argument("--limit", type=int, default=100)

    cone = commands.add_parser("cone")
    cone.add_argument("ra", type=float)
    cone.add_argument("dec", type=float)
    cone.add_argument("radius", type=float)
    cone.add_argument("--limit", type=int, default=100)

    args = parser.parse_args()

    if args.command == "name":
        result = search_name(args.name, args.limit)
    else:
        result = cone_search(
            args.ra, args.dec, args.radius, args.limit
        )

    print(json.dumps(result, indent=2))
