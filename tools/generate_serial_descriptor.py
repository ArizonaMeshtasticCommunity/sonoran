"""Emit a protobuf.js descriptor for the serial client API (#116).

The vendored config checker ships `meshtastic-proto.js`, and its own
header calls it "minimal, for DeviceProfile". Measured: 41 messages,
with `Config`, `ModuleConfig` and `DeviceProfile` present and
**`ToRadio`, `FromRadio`, `MeshPacket` and `Data` absent**. So the file
that #116 says already carries the schema does carry it for the upload
path and not for the serial one.

That file is upstream's, pinned at a commit and watched by
`vendor-pin.yml`. Editing it locally would be invisible to that check
and lost on the next bump, so this writes a SEPARATE file of ours
instead, generated from the same Python protobuf modules the ingest
already decodes with. One schema, two consumers, no hand-maintained
second copy to drift.

    uv run python tools/generate_serial_descriptor.py

The output is committed. Re-run it when the vendored Meshtastic
protobufs move.

**No `new Function` anywhere**, which is the constraint that shaped the
existing `generate_protobuf_static.sh`: this dashboard's `script-src`
carries no `unsafe-eval`, and protobuf.js's `Root.fromJSON` builds its
decoders reflectively rather than by compiling strings.
"""

import json
from pathlib import Path
from typing import Any

from google.protobuf.descriptor import Descriptor, EnumDescriptor, FieldDescriptor

from sonoran.meshtastic import (
    admin_pb2,
    channel_pb2,
    config_pb2,
    mesh_pb2,
    module_config_pb2,
    portnums_pb2,
    telemetry_pb2,
)

OUT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "sonoran"
    / "web"
    / "static"
    / "meshtastic-serial-proto.js"
)

# The modules the serial exchange needs. `mesh_pb2` carries ToRadio,
# FromRadio, MeshPacket and Data; the rest are what their fields point
# at. protobuf.js resolves names within the package, so a message whose
# dependency is missing fails at `fromJSON` rather than silently — see
# the round-trip check in `test_serial_descriptor.py`.
MODULES = (
    mesh_pb2,
    config_pb2,
    module_config_pb2,
    channel_pb2,
    telemetry_pb2,
    portnums_pb2,
    admin_pb2,
)

# protobuf.js spells the scalar types the way the .proto file does.
SCALARS = {
    FieldDescriptor.TYPE_DOUBLE: "double",
    FieldDescriptor.TYPE_FLOAT: "float",
    FieldDescriptor.TYPE_INT64: "int64",
    FieldDescriptor.TYPE_UINT64: "uint64",
    FieldDescriptor.TYPE_INT32: "int32",
    FieldDescriptor.TYPE_FIXED64: "fixed64",
    FieldDescriptor.TYPE_FIXED32: "fixed32",
    FieldDescriptor.TYPE_BOOL: "bool",
    FieldDescriptor.TYPE_STRING: "string",
    FieldDescriptor.TYPE_BYTES: "bytes",
    FieldDescriptor.TYPE_UINT32: "uint32",
    FieldDescriptor.TYPE_SFIXED32: "sfixed32",
    FieldDescriptor.TYPE_SFIXED64: "sfixed64",
    FieldDescriptor.TYPE_SINT32: "sint32",
    FieldDescriptor.TYPE_SINT64: "sint64",
}


def _field_type(field: FieldDescriptor) -> str:
    if field.type == FieldDescriptor.TYPE_MESSAGE:
        return field.message_type.name
    if field.type == FieldDescriptor.TYPE_ENUM:
        return field.enum_type.name
    return SCALARS[field.type]


def _field(field: FieldDescriptor) -> dict[str, Any]:
    out: dict[str, Any] = {"type": _field_type(field), "id": field.number}
    if field.label == FieldDescriptor.LABEL_REPEATED:
        out["rule"] = "repeated"
    if field.containing_oneof is not None:
        # protobuf.js reads membership from the `oneofs` table below,
        # but it still wants the field marked optional.
        out["rule"] = out.get("rule", "optional")
    return out


def _enum(enum: EnumDescriptor) -> dict[str, Any]:
    return {"values": {value.name: value.number for value in enum.values}}


def _message(message: Descriptor) -> dict[str, Any]:
    out: dict[str, Any] = {"fields": {f.json_name: _field(f) for f in message.fields}}
    oneofs = {
        oneof.name: {"oneof": [field.json_name for field in oneof.fields]}
        for oneof in message.oneofs
    }
    if oneofs:
        out["oneofs"] = oneofs
    nested: dict[str, Any] = {}
    for inner in message.nested_types:
        # Map entries are protobuf's internal representation of a map
        # field; protobuf.js builds them itself.
        if inner.GetOptions().map_entry:
            continue
        nested[inner.name] = _message(inner)
    for inner_enum in message.enum_types:
        nested[inner_enum.name] = _enum(inner_enum)
    if nested:
        out["nested"] = nested
    return out


def _reachable(root: Descriptor, seen: dict[str, Any]) -> None:
    """Collect a message and everything its fields can reach.

    A hand-written module list is how this went wrong first time:
    `AdminMessage` was included and `DeviceConnectionStatus` was not,
    and protobuf.js failed at `Root.fromJSON` with "no such Type or
    Enum" -- loudly, which is the one good thing about it. Walking the
    fields instead means the closure cannot be incomplete.
    """
    if root.name in seen:
        return
    seen[root.name] = _message(root)
    for field in root.fields:
        if field.type == FieldDescriptor.TYPE_MESSAGE:
            inner = field.message_type
            if inner.GetOptions().map_entry:
                # A map's value can still be a message that needs including.
                value = inner.fields_by_name.get("value")
                if value is not None and value.type == FieldDescriptor.TYPE_MESSAGE:
                    _reachable(value.message_type, seen)
                continue
            _reachable(inner, seen)
        elif field.type == FieldDescriptor.TYPE_ENUM:
            seen.setdefault(field.enum_type.name, _enum(field.enum_type))


# What the serial exchange starts from. Everything else is pulled in by
# walking their fields, so this list is the only thing to maintain.
ROOTS = ("ToRadio", "FromRadio", "MeshPacket", "Data", "Channel", "AdminMessage")


def build() -> dict[str, Any]:
    """Every message and enum reachable from the serial roots."""
    seen: dict[str, Any] = {}
    for name in ROOTS:
        for module in MODULES:
            message = module.DESCRIPTOR.message_types_by_name.get(name)
            if message is not None:
                _reachable(message, seen)
                break
        else:
            raise SystemExit(f"{name} is in none of the modules; the schema moved")
    # Top-level enums a caller may need by name even when no field
    # points at one directly -- PortNum is how a reader labels a packet.
    for module in MODULES:
        for name, enum in module.DESCRIPTOR.enum_types_by_name.items():
            seen.setdefault(name, _enum(enum))
    return {"nested": {"meshtastic": {"nested": seen}}}


def main() -> None:
    descriptor = build()
    body = json.dumps(descriptor, indent=2, sort_keys=True)
    OUT.write_text(
        "/*\n"
        " * Meshtastic's schema for the serial client API (#116).\n"
        " *\n"
        " * GENERATED by tools/generate_serial_descriptor.py from the same\n"
        " * Python protobuf modules the ingest decodes with. Do not edit by\n"
        " * hand -- re-run the tool.\n"
        " *\n"
        " * This exists because the vendored config checker's own descriptor\n"
        " * is minimal by design: it carries Config, ModuleConfig and\n"
        " * DeviceProfile for the file-upload path, and NOT ToRadio,\n"
        " * FromRadio, MeshPacket or Data. That file is pinned upstream and\n"
        " * watched by vendor-pin.yml, so it is not ours to extend.\n"
        " *\n"
        " * Loaded with protobuf.js `Root.fromJSON`, which builds its\n"
        " * decoders reflectively. Nothing here calls `Function`, so the\n"
        " * page's `script-src` needs no `unsafe-eval`.\n"
        " */\n"
        f"window.MeshtasticSerialProto = {body};\n",
        encoding="utf-8",
    )
    count = len(descriptor["nested"]["meshtastic"]["nested"])
    print(f"wrote {OUT.relative_to(Path.cwd())} with {count} messages and enums")


if __name__ == "__main__":
    main()
