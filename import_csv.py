import csv
import sys

import psycopg
from psycopg import sql

# Replace these with the exact CSV header names.
NAME_COL = "FIRST"
RA_COL = "RAJ2000"
DEC_COL = "DEJ2000"

path = sys.argv[1]

with open(path, newline="", encoding="utf-8-sig") as f:
    reader = csv.reader(f)
    headers = next(reader)

    if not headers or any(not h for h in headers):
        raise ValueError("CSV must have nonempty column names")
    if len(headers) != len(set(headers)):
        raise ValueError("CSV column names must be unique")
    if any(len(h.encode("utf-8")) > 63 for h in headers):
        raise ValueError("Map long column names to shorter SQL identifiers")

    for required in (NAME_COL, RA_COL, DEC_COL):
        if required not in headers:
            raise ValueError(f"Missing configured column: {required}")

    with psycopg.connect("") as conn:
        with conn.cursor() as cur:
            # Preserve every CSV field without guessing its type.
            definitions = sql.SQL(", ").join(
                sql.SQL("{} text").format(sql.Identifier(h))
                for h in headers
            )
            cur.execute(
                sql.SQL("CREATE TABLE first_raw ({})").format(definitions)
            )

            statement = sql.SQL("COPY first_raw ({}) FROM STDIN").format(
                sql.SQL(", ").join(map(sql.Identifier, headers))
            )

            count = 0
            with cur.copy(statement) as copy:
                for row in reader:
                    if len(row) != len(headers):
                        raise ValueError(
                            f"Wrong field count near CSV line {reader.line_num}"
                        )
                    copy.write_row([None if v == "" else v for v in row])
                    count += 1

            cur.execute("""
                CREATE TABLE sources (
                    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    name text NOT NULL,
                    ra_deg double precision NOT NULL
                        CHECK (ra_deg >= 0 AND ra_deg < 360),
                    dec_deg double precision NOT NULL
                        CHECK (dec_deg >= -90 AND dec_deg <= 90),
                    attributes jsonb NOT NULL
                )
            """)

            cur.execute(
                sql.SQL("""
                    INSERT INTO sources
                        (name, ra_deg, dec_deg, attributes)
                    SELECT
                        {name},
                        {ra}::double precision,
                        {dec}::double precision,
                        to_jsonb(r)
                    FROM first_raw AS r
                """).format(
                    name=sql.Identifier(NAME_COL),
                    ra=sql.Identifier(RA_COL),
                    dec=sql.Identifier(DEC_COL),
                )
            )

print(f"Imported {count} rows")
