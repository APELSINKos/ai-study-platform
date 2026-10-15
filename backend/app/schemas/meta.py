from typing import Literal

from pydantic import BaseModel, Field

type AiMode = Literal["offline", "live"]


class AiInfo(BaseModel):
    mode: AiMode = Field(
        description="offline: the built-in analysis and embeddings, which need no API key;"
        " live: the configured models."
    )
    chat_model: str = Field(description="The model that analyses documents.")
    embedding_model: str = Field(description="The model that embeds chunks for search.")


class MetaOut(BaseModel):
    max_upload_bytes: int = Field(description="The largest file that can be uploaded.")
    allowed_extensions: list[str] = Field(
        description="File name extensions that can be uploaded, in lower case with the dot."
    )
    max_pdf_pages: int = Field(description="A PDF with more pages is not processed.")
    max_active_documents_per_user: int = Field(
        description="How many of a user's documents may wait for, or go through, processing"
        " at once."
    )
    max_storage_bytes_per_user: int = Field(description="The total size of a user's files.")
    ai: AiInfo
