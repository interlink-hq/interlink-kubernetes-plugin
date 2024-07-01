"""
Classes to model API response objects
"""

from typing import Any

from pydantic import BaseModel, Field  # pylint: disable=no-name-in-module


class ApiResponseDto(BaseModel):
    detail: Any = Field(...)

    class Config:
        json_schema_extra = {
            "example": {
                "detail": "Api response details",
            }
        }


class ApiErrorResponseDto(ApiResponseDto):
    class Config:
        json_schema_extra = {
            "example": {
                "detail": "Api error details",
            }
        }


class Api1XXResponseDto(ApiErrorResponseDto):
    pass


class Api3XXResponseDto(ApiErrorResponseDto):
    pass


class Api4XXResponseDto(ApiErrorResponseDto):
    pass


class Api5XXResponseDto(ApiErrorResponseDto):
    pass
