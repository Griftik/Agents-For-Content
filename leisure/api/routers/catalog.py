from fastapi import APIRouter

from leisure.core.catalog import (ALL_CATS, AREA_OPTIONS, BUSINESS_CATS, CATS, COMPANY_OPTIONS, KNOWN_TAGS, REASONS,
                                  SLOTS, VALUE_CLUSTERS, VALUE_SHORT, VALUES, default_profile)

from ..schemas import CatalogOut

router = APIRouter(prefix="/api/catalog", tags=["справочники"])


@router.get("", response_model=CatalogOut)
def catalog() -> dict:
    return {"values": VALUES, "categories": CATS, "business_categories": BUSINESS_CATS, "tags": sorted(KNOWN_TAGS),
            "reasons": REASONS, "company": COMPANY_OPTIONS, "areas": AREA_OPTIONS, "times": SLOTS,
            "default_profile": default_profile(), "value_clusters": VALUE_CLUSTERS, "value_short": VALUE_SHORT}
