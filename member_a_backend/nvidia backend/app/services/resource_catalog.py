"""Trusted immutable metadata only: no document contents, paths, or resource reads."""

import re

from pydantic import Field, model_validator
from sqlalchemy import select

from app.agent_schemas import IdentityModel, Reference, ResourceVersion, TaskScope
from app.models import DocumentResource
from app.services.fixture_storage import STORAGE_REFERENCES

MANAGED_RESOURCE = re.compile(r"resource_[0-9a-f]{32}\Z", re.ASCII)


class CatalogResource(ResourceVersion):
    owner_id: Reference


class ResourceCatalog(IdentityModel):
    resources: tuple[CatalogResource, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def unique_resources(self):
        ids = [item.resource_id for item in self.resources]
        if len(ids) != len(set(ids)):
            raise ValueError("Catalog IDs must be unique")
        return self

    def validates(self, scope: TaskScope, owner_id: str) -> bool:
        return all(
            any(
                item.owner_id == owner_id
                and item.resource_id == pin.resource_id
                and item.version_ref == pin.version_ref
                and item.classification == pin.classification
                for item in self.resources
            )
            for pin in scope.resource_versions
        )

    def resolve(self, db, scope: TaskScope, owner_id: str) -> "ResourceCatalog":
        """Refresh managed IDs under the caller's task transaction, even for old snapshots."""
        managed = [ref for ref in scope.resource_ids if MANAGED_RESOURCE.fullmatch(ref)]
        rows = (
            list(
                db.scalars(
                    select(DocumentResource)
                    .where(DocumentResource.resource_ref.in_(managed))
                    .order_by(DocumentResource.resource_ref)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
            if managed
            else []
        )
        resources = [
            item
            for item in self.resources
            if item.resource_id in scope.resource_ids
            and not MANAGED_RESOURCE.fullmatch(item.resource_id)
        ]
        resources.extend(
            CatalogResource(
                resource_id=row.resource_ref,
                owner_id=row.owner_ref,
                version_ref=row.version_ref,
                classification=row.classification,
            )
            for row in rows
            if row.active
            and row.owner_ref == owner_id
            and row.resource_type == "SYNTHETIC_TEXT"
            and row.storage_reference in STORAGE_REFERENCES
            and re.fullmatch(r"[0-9a-f]{64}", row.content_digest)
        )
        return ResourceCatalog(resources=tuple(resources))


EMPTY_CATALOG = ResourceCatalog()


def get_resource_catalog() -> ResourceCatalog:
    # Managed resources are resolved inside task transactions, never from HTTP claims.
    return EMPTY_CATALOG
