from .company import Company
from .user import User
from .rbac import Role, Permission, user_role, role_permission
from .document import Document, DocumentVersion, DocumentStatusType
from .document_access import UserDocumentAccess
from .chunk import Chunk
from .comment import Comment, CommentType
from .comment_file import CommentFile
from .chat import Chat, ChatMessage
from .image_chunk import ImageChunk
from .ai_model import ChatAIModels
from .embedding_config import EmbeddingConfig
from .file_asset import FileAsset, FileAssetStatus
from .task_result import TaskResult

from model_management.models import (
    ManagedModel,
    ModelDocumentLink,
    ModelCommentLink,
    ModelReceiptLink,
)

from tag_management.models import (
    TagModelLink,
    TagDocumentLink,
    TagCommentLink,
    TagReceiptLink,
)

from financial_management.models import (
    FinancialAccessMethod,
    FinancialCard,
    FinancialCustomer,
    FinancialReceipt,
    FinancialReceiptFile,
    FinancialReceiptCommentLink,
    FinancialDirection,
)

from property_management.models import (
    OwnedProperty,
    WarehouseItem,
)

# buying_management removed in Phase 0.2 — replaced by purchase_management
# The buying_management/ folder remains on disk but is no longer imported.
# Tables were dropped in migration a2_phase_0_2_purchase.

from supplier_management.models import (
    Supplier,
    SupplierContact,
    SupplierCategory,
    SupplierDocument,
    SupplierEvaluation,
)

from material_management.models import (
    ItemCategory,
    Unit,
    Item,
    ItemAlternative,
    ItemDocument,
)

from requisition_management.models import (
    MaterialRequisition,
    MaterialRequisitionItem,
    MaterialRequisitionStatusHistory,
)

from rfq_management.models import (
    RequestForQuotation,
    RFQSupplier,
    RFQItem,
    QuotationResponse,
    QuotationResponseItem,
)

from purchase_management.models import (
    PurchaseOrder,
    PurchasePhase,
    PurchasePhaseItem,
    PurchaseOrderCost,
    PurchaseOrderReceiptLink,
)

from shared.currency.models import (
    Currency,
    ExchangeRate,
)

from document_intelligence.models import (
    DocumentIntelligenceJob,
    DocumentPageArtifact,
    DocumentMethodRun,
    DocumentSegment,
    DocumentSegmentSuggestion,
    DIModelCreationSuggestion,
    DocumentIntelligenceLabel,
)

__all__ = [
    "Company",
    "User",
    "Role",
    "Permission",
    "user_role",
    "role_permission",
    "Document",
    "DocumentVersion",
    "UserDocumentAccess",
    "Chunk",
    "Comment",
    "CommentFile",
    "ImageChunk",
    "ChatAIModels",
    "EmbeddingConfig",
    "FileAsset",
    "FileAssetStatus",
    "TaskResult",
    "CommentType",
    "DocumentStatusType",
    "Chat",
    "ChatMessage",
    "ManagedModel",
    "ModelDocumentLink",
    "ModelCommentLink",
    "ModelReceiptLink",
    "TagModelLink",
    "TagDocumentLink",
    "TagCommentLink",
    "TagReceiptLink",
    "FinancialAccessMethod",
    "FinancialCard",
    "FinancialCustomer",
    "FinancialReceipt",
    "FinancialReceiptFile",
    "FinancialReceiptCommentLink",
    "FinancialDirection",
    "WarehouseItem",
    "OwnedProperty",
    "Supplier",
    "SupplierContact",
    "SupplierCategory",
    "SupplierDocument",
    "SupplierEvaluation",
    "ItemCategory",
    "Unit",
    "Item",
    "ItemAlternative",
    "ItemDocument",
    "MaterialRequisition",
    "MaterialRequisitionItem",
    "MaterialRequisitionStatusHistory",
    "RequestForQuotation",
    "RFQSupplier",
    "RFQItem",
    "QuotationResponse",
    "QuotationResponseItem",
    "PurchaseOrder",
    "PurchasePhase",
    "PurchasePhaseItem",
    "PurchaseOrderCost",
    "PurchaseOrderReceiptLink",
    "Currency",
    "ExchangeRate",
    "DocumentIntelligenceJob",
    "DocumentPageArtifact",
    "DocumentMethodRun",
    "DocumentSegment",
    "DocumentSegmentSuggestion",
    "DIModelCreationSuggestion",
    "DocumentIntelligenceLabel",
]
