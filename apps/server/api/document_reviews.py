from uuid import UUID

from fastapi import APIRouter, Depends, Query

from apps.server.api.dependencies import identity_dependencies
from apps.server.application.document_reviews import DocumentReviewService
from packages.contracts import Error
from packages.contracts.document_reviews import AssignmentCandidatePage, DocumentReview


def document_review_router(orders):
    router = APIRouter(prefix="/api/v1/documents", tags=["orders"],
                       responses={c: {"model": Error} for c in (401, 403, 404, 409, 422, 503)})
    _, authorization = identity_dependencies(orders.identity)
    service = DocumentReviewService(orders)

    @router.get("/{document_id}/approval-snapshots", response_model=DocumentReview)
    def review(document_id: UUID, auth=Depends(authorization)):
        return service.review(auth, document_id)

    @router.get("/{document_id}/assignment-candidates", response_model=AssignmentCandidatePage)
    def candidates(document_id: UUID, q: str = Query(default="", max_length=100),
                   after: UUID | None = None, limit: int = Query(default=25, ge=1, le=100),
                   auth=Depends(authorization)):
        return service.candidates(auth, document_id, q.strip(), after, limit)

    return router
