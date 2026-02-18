"""PEP 440 version type with Pydantic serialization support."""

from typing import Annotated

from packaging.version import Version
from pydantic import PlainSerializer, PlainValidator

VersionType = Annotated[
    Version,
    PlainValidator(lambda v: Version(v) if isinstance(v, str) else v),
    PlainSerializer(lambda v: str(v)),
]
