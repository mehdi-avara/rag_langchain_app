from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Literal

from pydantic import BaseModel, Field

from Models import CommentType
from financial_management.schemas import FinancialReceiptCreate, FinancialReceiptOut
from schemas.comment import CommentCreate
from schemas.search import ModelSemanticSearchResponse


class ModelCreate(BaseModel):
    manufacturer: str
    model: str
    description: Optional[str] = None
    type: Optional[str] = None


class ModelUpdate(BaseModel):
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None


class ModelOut(BaseModel):
    id: int
    manufacturer: str
    model: str
    description: Optional[str] = None
    type: Optional[str] = None
    owner_id: int
    created_at: datetime
    updated_at: datetime
    doc_ids: List[int] = Field(default_factory=list)
    comment_ids: List[int] = Field(default_factory=list)
    receipt_ids: List[int] = Field(default_factory=list)

    class Config:
        orm_mode = True


class ModelListOut(BaseModel):
    id: int
    manufacturer: str
    model: str
    description: Optional[str] = None
    type: Optional[str] = None
    owner_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class ModelDocLinkCreate(BaseModel):
    document_id: int
    note: Optional[str] = None


class ModelCommentLinkCreate(BaseModel):
    comment_id: int
    note: Optional[str] = None


class ModelCreateCommentAndLinkRequest(BaseModel):
    payload: CommentCreate
    link_description: Optional[str] = None


class ModelReceiptLinkCreate(BaseModel):
    receipt_id: int
    note: Optional[str] = None


class ModelCreateReceiptAndLinkRequest(BaseModel):
    payload: FinancialReceiptCreate
    link_description: Optional[str] = None


class ModelDocLinkOut(BaseModel):
    model_id: int
    document_id: int
    linked_by_user_id: int
    note: Optional[str] = None
    created_at: datetime

    class Config:
        orm_mode = True


class ModelCommentLinkOut(BaseModel):
    model_id: int
    comment_id: int
    linked_by_user_id: int
    note: Optional[str] = None
    created_at: datetime

    class Config:
        orm_mode = True


class ModelReceiptLinkOut(BaseModel):
    model_id: int
    receipt_id: int
    linked_by_user_id: int
    note: Optional[str] = None
    created_at: datetime

    class Config:
        orm_mode = True


class ModelDocumentOut(BaseModel):
    id: int
    filename: str
    n_pages: int
    n_chunks: int
    created_at: datetime
    status: str
    abstract: Optional[str] = None
    file_path: Optional[str] = None
    note: Optional[str] = None
    linked_at: Optional[datetime] = None


class ModelCommentOut(BaseModel):
    id: int
    user_id: int
    title: str
    type: CommentType
    content: str
    created_at: datetime
    note: Optional[str] = None
    linked_at: Optional[datetime] = None


class ModelReceiptOut(BaseModel):
    receipt: FinancialReceiptOut
    note: Optional[str] = None
    linked_at: Optional[datetime] = None


class ModelReceiptSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    mode: Literal["keyword", "vector", "hybrid"] = "hybrid"
    limit: int = Field(default=50, ge=1, le=200)


class ModelReceiptSummaryOut(BaseModel):
    total_receipts: int
    total_input_amount: Decimal
    total_output_amount: Decimal
    total_cost_amount: Decimal
    net_amount: Decimal


class ModelAskRequest(BaseModel):
    question: str
    mode: Literal["keyword", "vector", "hybrid"] = "hybrid"
    route: str = "full"
    scope: Literal["docs", "comments", "both"] = "both"
    types: List[CommentType] = Field(default_factory=list)


class ModelAskMultiRequest(ModelAskRequest):
    model_ids: List[int] = Field(default_factory=list)


class ModelAskResponse(BaseModel):
    answer: str
    citations: List[int] = Field(default_factory=list)
    used_chunk_ids: List[int] = Field(default_factory=list)
    used_comment_ids: List[int] = Field(default_factory=list)
    references: ModelSemanticSearchResponse
