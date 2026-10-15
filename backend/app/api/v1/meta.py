from fastapi import APIRouter

from app.api.deps import SettingsDep
from app.core.config import Settings
from app.documents.validation import ALLOWED_EXTENSIONS
from app.llm.mock_provider import MOCK_ANALYSIS_MODEL, MOCK_EMBEDDING_MODEL
from app.schemas.meta import AiInfo, MetaOut

router = APIRouter(prefix="/meta", tags=["meta"])


def _ai_info(settings: Settings) -> AiInfo:
    llm_provider = settings.resolved_llm_provider
    embedding_provider = settings.resolved_embedding_provider
    return AiInfo(
        mode="offline" if "mock" in (llm_provider, embedding_provider) else "live",
        chat_model=settings.llm_model if llm_provider == "openai" else MOCK_ANALYSIS_MODEL,
        embedding_model=(
            settings.embedding_model if embedding_provider == "openai" else MOCK_EMBEDDING_MODEL
        ),
    )


@router.get("", summary="Upload limits, accepted file types and the AI models in use")
def get_meta(settings: SettingsDep) -> MetaOut:
    """Public, so the web app can check a file before it is sent. Names the models in use,
    never their keys or addresses."""
    return MetaOut(
        max_upload_bytes=settings.max_upload_bytes,
        allowed_extensions=list(ALLOWED_EXTENSIONS),
        max_pdf_pages=settings.max_pdf_pages,
        max_active_documents_per_user=settings.max_active_documents_per_user,
        max_storage_bytes_per_user=settings.max_storage_bytes_per_user,
        ai=_ai_info(settings),
    )
