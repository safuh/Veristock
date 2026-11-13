"""Tenant-scoped upload and retrieval of stocktake image evidence."""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import FileResponse

from veristock.core.config import Settings
from veristock.identity.authorization import Organization
from veristock.identity.authorization_dependencies import (
    get_current_user,
    get_db_session,
    require_permission,
)
from veristock.identity.models import User
from veristock.stocktaking.evidence import (
    EvidenceValidationError,
    evidence_path,
    inspect_image,
    persist_image,
)
from veristock.stocktaking.evidence_models import StocktakeEvidence
from veristock.stocktaking.models import (
    Stocktake,
    StocktakeObservation,
    StocktakeRound,
)

router = APIRouter(prefix="/stocktakes", tags=["stocktaking evidence"])
EvidenceUploader = Annotated[Organization, Depends(require_permission("stocktake.count"))]
EvidenceReader = Annotated[Organization, Depends(require_permission("stocktake.read"))]


class StocktakeEvidenceSchema(BaseModel):
    """Safe metadata returned to authorized tenant members."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    stocktake_id: str
    round_id: str
    observation_id: str
    media_type: str
    byte_size: int
    sha256_digest: str
    original_filename: str | None
    uploaded_by_user_id: str
    created_at: datetime


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _filename(value: str | None) -> str | None:
    if not value:
        return None
    name = Path(value.replace("\\", "/")).name
    safe = "".join(char for char in name if char.isalnum() or char in "._- ")[:255]
    return safe or None


@router.post(
    "/{stocktake_id}/observations/{observation_id}/evidence",
    response_model=StocktakeEvidenceSchema,
    status_code=201,
)
async def upload_stocktake_evidence(
    stocktake_id: str,
    observation_id: str,
    request: Request,
    organization: EvidenceUploader,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    content_type: Annotated[str | None, Header(alias="Content-Type")] = None,
    filename: str | None = Query(default=None, max_length=1024),
) -> StocktakeEvidence:
    """Upload a bounded image to an observation in the active count round."""
    stocktake = await session.scalar(
        select(Stocktake).where(
            Stocktake.id == stocktake_id,
            Stocktake.organization_id == organization.id,
            Stocktake.status == "open",
        )
    )
    if stocktake is None:
        raise HTTPException(status_code=404, detail="Open stocktake not found")
    observation = await session.scalar(
        select(StocktakeObservation).where(
            StocktakeObservation.id == observation_id,
            StocktakeObservation.organization_id == organization.id,
            StocktakeObservation.stocktake_id == stocktake.id,
        )
    )
    if observation is None:
        raise HTTPException(status_code=404, detail="Stocktake observation not found")
    round_record = await session.scalar(
        select(StocktakeRound).where(
            StocktakeRound.id == observation.round_id,
            StocktakeRound.organization_id == organization.id,
            StocktakeRound.stocktake_id == stocktake.id,
            StocktakeRound.status == "open",
        )
    )
    if round_record is None:
        raise HTTPException(
            status_code=409,
            detail="Evidence can only be added to an open count round",
        )

    settings = _settings(request)
    maximum = settings.stocktake_evidence_max_bytes
    declared_length = request.headers.get("content-length")
    if declared_length and declared_length.isdigit() and int(declared_length) > maximum:
        raise HTTPException(status_code=413, detail="Evidence image exceeds the upload limit")

    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > maximum:
            raise HTTPException(status_code=413, detail="Evidence image exceeds the upload limit")
        chunks.append(chunk)
    content = b"".join(chunks)
    try:
        media_type, suffix = inspect_image(content, media_type)
    except EvidenceValidationError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc

    storage_root = settings.stocktake_evidence_storage_dir
    storage_key, digest = await asyncio.to_thread(persist_image, storage_root, content, suffix)
    record = StocktakeEvidence(
        id=str(uuid4()),
        organization_id=organization.id,
        stocktake_id=stocktake.id,
        round_id=round_record.id,
        observation_id=observation.id,
        storage_key=storage_key,
        media_type=media_type,
        byte_size=len(content),
        sha256_digest=digest,
        original_filename=_filename(filename or request.headers.get("x-filename")),
        uploaded_by_user_id=user.id,
    )
    session.add(record)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        await asyncio.to_thread(
            lambda: evidence_path(storage_root, storage_key).unlink(missing_ok=True)
        )
        raise
    await session.refresh(record)
    return record


@router.get(
    "/{stocktake_id}/observations/{observation_id}/evidence",
    response_model=list[StocktakeEvidenceSchema],
)
async def list_stocktake_evidence(
    stocktake_id: str,
    observation_id: str,
    organization: EvidenceReader,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[StocktakeEvidence]:
    observation = await session.scalar(
        select(StocktakeObservation).where(
            StocktakeObservation.id == observation_id,
            StocktakeObservation.organization_id == organization.id,
            StocktakeObservation.stocktake_id == stocktake_id,
        )
    )
    if observation is None:
        raise HTTPException(status_code=404, detail="Stocktake observation not found")
    records = await session.scalars(
        select(StocktakeEvidence)
        .where(
            StocktakeEvidence.organization_id == organization.id,
            StocktakeEvidence.stocktake_id == stocktake_id,
            StocktakeEvidence.observation_id == observation_id,
        )
        .order_by(StocktakeEvidence.created_at)
    )
    return list(records.all())


@router.get("/{stocktake_id}/evidence/{evidence_id}/content")
async def get_stocktake_evidence_content(
    stocktake_id: str,
    evidence_id: str,
    request: Request,
    organization: EvidenceReader,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    record = await session.scalar(
        select(StocktakeEvidence).where(
            StocktakeEvidence.id == evidence_id,
            StocktakeEvidence.stocktake_id == stocktake_id,
            StocktakeEvidence.organization_id == organization.id,
        )
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Stocktake evidence not found")
    try:
        path = evidence_path(_settings(request).stocktake_evidence_storage_dir, record.storage_key)
    except EvidenceValidationError as exc:
        raise HTTPException(status_code=500, detail="Evidence storage metadata is invalid") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Evidence content is unavailable")
    return FileResponse(
        path,
        media_type=record.media_type,
        filename=f"{record.id}{Path(record.storage_key).suffix}",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )
