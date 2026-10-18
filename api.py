from typing import Annotated

from fastapi import FastAPI, Query

from queries import cone_search, search_name

app = FastAPI(title="FIRST Catalog API")


@app.get("/sources")
def sources_by_name(
    name: Annotated[str, Query(min_length=1, max_length=255)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
):
    rows = search_name(name, limit)
    return {
        "count": len(rows),
        "limit": limit,
        "results": rows,
    }


@app.get("/sources/cone")
def sources_in_cone(
    ra: Annotated[
        float, Query(ge=0, lt=360, allow_inf_nan=False)
    ],
    dec: Annotated[
        float, Query(ge=-90, le=90, allow_inf_nan=False)
    ],
    radius: Annotated[
        float, Query(gt=0, le=180, allow_inf_nan=False)
    ],
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
):
    rows = cone_search(ra, dec, radius, limit)
    return {
        "center": {"ra_deg": ra, "dec_deg": dec},
        "radius_deg": radius,
        "count": len(rows),
        "limit": limit,
        "results": rows,
    }
