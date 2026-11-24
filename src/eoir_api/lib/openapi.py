from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, get_args, get_origin

from litestar.openapi.plugins import JsonRenderPlugin
from litestar.params import ParameterKwarg
from litestar.plugins import OpenAPISchemaPlugin
from litestar.typing import FieldDefinition

if TYPE_CHECKING:
    from litestar import Request
    from litestar._openapi.schema_generation import SchemaCreator
    from litestar.openapi.spec import Schema


def description_of(annotation: Any) -> str | None:
    """Return the first string in an ``Annotated`` type's metadata."""
    if get_origin(annotation) is not Annotated:
        return None
    return next((m for m in get_args(annotation)[1:] if isinstance(m, str)), None)


class DescribedTypedDictPlugin(OpenAPISchemaPlugin):
    """Document a TypedDict, describing each field by the string it is annotated with.

    Litestar's own TypedDict plugin has no way to describe a field.
    """

    def is_plugin_supported_field(self, field_definition: FieldDefinition) -> bool:
        return field_definition.is_typeddict_type

    def to_openapi_schema(
        self, field_definition: FieldDefinition, schema_creator: SchemaCreator
    ) -> Schema:
        hints = field_definition.get_type_hints(
            include_extras=True, resolve_generics=True
        )
        properties = {}
        for name, annotation in hints.items():
            description = description_of(annotation)
            properties[name] = FieldDefinition.from_annotation(
                annotation,
                name=name,
                kwarg_definition=ParameterKwarg(description=description)
                if description
                else None,
            )
        return schema_creator.create_component_schema(
            field_definition,
            required=sorted(field_definition.type_.__required_keys__),
            property_fields=properties,
        )


BASE_URL_PLACEHOLDER = "{base_url}"


class BaseURLJsonRenderPlugin(JsonRenderPlugin):
    """Render the OpenAPI schema as JSON, filling the description's base URL from the request."""

    def render(self, request: Request, openapi_schema: dict[str, Any]) -> bytes:
        info = openapi_schema["info"]
        base_url = str(request.base_url).rstrip("/")
        description = info["description"].replace(BASE_URL_PLACEHOLDER, base_url)
        return super().render(
            request,
            {**openapi_schema, "info": {**info, "description": description}},
        )
