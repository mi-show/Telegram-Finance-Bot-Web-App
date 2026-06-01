from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .classifier import CategoryClassifier

__all__ = ["CategoryClassifier"]


def __getattr__(name: str):
    if name == "CategoryClassifier":
        from .classifier import CategoryClassifier

        return CategoryClassifier
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
