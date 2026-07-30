from __future__ import annotations

from assistant.module_interface import (
    Candidate,
    FunctionSearchProvider,
    ResourceSpec,
    register_resource,
)
from assistant.registry import register_toolset
from shared.commerce_assistant import (
    ConfiguredCommerceToolSet,
    PayloadField,
    SearchSpec,
    WriteSpec,
)

from .services import search_models_for_assistant


MODULE = "model_management"
API_PREFIX = "/models"

P_READ = "models:read"
P_SEARCH = "models:search"
P_ASK = "models:ask"
P_CREATE = "models:create"
P_UPDATE = "models:update"


def _search_model_hits(
    db,
    current_user,
    query_text,
    mode="hybrid",
    model_ids=None,
    limit=10,
):
    # Managed-model lookup is currently keyword-backed. Keep the configured
    # assistant signature so the implementation can adopt hybrid search later
    # without changing the tool contract.
    del mode
    return search_models_for_assistant(
        db=db,
        current_user=current_user,
        query_text=query_text,
        ids=model_ids,
        limit=limit,
    )


def _model_to_candidate(model) -> Candidate:
    manufacturer = getattr(model, "manufacturer", None)
    model_name = getattr(model, "model", None)
    model_type = getattr(model, "type", None)
    label = " - ".join(
        part
        for part in (manufacturer, model_name, model_type)
        if part
    )
    return Candidate(
        id=model.id,
        match_text=model_name or manufacturer or "",
        label=label or f"Model #{model.id}",
        data={
            "id": model.id,
            "manufacturer": manufacturer,
            "model": model_name,
            "type": model_type,
            "description": getattr(model, "description", None),
        },
    )


def register_model_resources() -> None:
    register_resource(
        ResourceSpec(
            key="managed_model",
            read_permission=P_READ,
            provider=FunctionSearchProvider(
                search_models_for_assistant,
                _model_to_candidate,
            ),
            create_permission=P_CREATE,
            create_endpoint=f"{API_PREFIX}/",
            suggestion_from=lambda raw, slots: {
                "manufacturer": slots.get("manufacturer")
                or slots.get("make")
                or slots.get("brand")
                or "",
                "model": raw,
                "type": slots.get("model_type")
                or slots.get("equipment_type")
                or slots.get("type"),
            },
        )
    )


class ModelManagementAssistantToolSet(
    ConfiguredCommerceToolSet
):
    module = MODULE
    module_display_title = "Equipment Model Management"
    module_description = (
        "Find, ask about, and prepare create or update drafts for "
        "equipment manufacturer/model records. These are equipment "
        "models, not AI models, stock items, or physical assets."
    )
    module_specialist_notes = (
        "A managed model is an equipment type identified by its "
        "manufacturer and model name.",
        "Creating a model does not create a material item or asset.",
        "The assistant prepares drafts only; the model endpoint "
        "performs the write after review.",
    )

    search_specs = (
        SearchSpec(
            intent="search_models",
            description=(
                "Find equipment models by manufacturer, model name, "
                "equipment type, or description."
            ),
            permission=P_SEARCH,
            search_fn=_search_model_hits,
            resource_type="model",
            id_attr="id",
            id_param="model_ids",
            title_fields=("manufacturer", "model", "type"),
            module=MODULE,
            ask_intent="ask_models",
            ask_description=(
                "Answer a grounded question using equipment-model "
                "records as references."
            ),
            ask_permission=P_ASK,
            citation_prefix="model",
            slot_rules=(
                "Treat model as an equipment manufacturer/model record, "
                "not an AI or machine-learning model.",
            ),
            examples=(
                "Find Flowserve pump models.",
                "مدل‌های پمپ فلوسرو را پیدا کن.",
            ),
        ),
    )

    write_specs = (
        WriteSpec(
            intent="add_model",
            description=(
                "Create an equipment manufacturer/model draft."
            ),
            permission=P_CREATE,
            target_action="create_model",
            method="POST",
            endpoint=f"{API_PREFIX}/",
            required=("manufacturer", "model"),
            fields=(
                PayloadField(
                    "manufacturer",
                    aliases=("manufacturer_name", "make", "brand"),
                ),
                PayloadField(
                    "model",
                    aliases=(
                        "model_name",
                        "model_number",
                        "equipment_model",
                    ),
                ),
                PayloadField(
                    "description",
                    aliases=("model_description", "details"),
                ),
                PayloadField(
                    "type",
                    aliases=("model_type", "equipment_type"),
                ),
            ),
            slot_rules=(
                "manufacturer and model are required.",
                "Put the equipment class, such as pump or motor, in type.",
            ),
            examples=(
                "Create a Flowserve Mark 3 pump model.",
                "مدل پمپ Mark 3 از سازنده Flowserve را ایجاد کن.",
            ),
        ),
        WriteSpec(
            intent="update_model",
            description=(
                "Update an existing equipment-model draft."
            ),
            permission=P_UPDATE,
            target_action="update_model",
            method="PATCH",
            endpoint=f"{API_PREFIX}/{{entity_id}}",
            id_aliases=("model_id", "id"),
            fields=(
                PayloadField(
                    "manufacturer",
                    aliases=("manufacturer_name", "make", "brand"),
                ),
                PayloadField(
                    "model",
                    aliases=(
                        "model_name",
                        "model_number",
                        "equipment_model",
                    ),
                ),
                PayloadField(
                    "description",
                    aliases=("model_description", "details"),
                ),
                PayloadField(
                    "type",
                    aliases=("model_type", "equipment_type"),
                ),
            ),
            examples=(
                "Update model 42 and set its type to centrifugal pump.",
                "نوع مدل 42 را پمپ سانتریفیوژ قرار بده.",
            ),
        ),
    )


def register() -> ModelManagementAssistantToolSet:
    toolset = ModelManagementAssistantToolSet()
    register_toolset(toolset)
    register_model_resources()
    return toolset


register()
