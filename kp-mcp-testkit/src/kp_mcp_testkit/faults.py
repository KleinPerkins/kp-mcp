"""Fault-injection context manager.

Concrete, generic, no Google deps.
Patches a callable to raise a given exception unconditionally or after N successful calls.
"""

import importlib
import unittest.mock
from contextlib import contextmanager
from typing import Any, Callable, Generator, Type


def _validate_after_calls(after_calls: int) -> None:
    if after_calls < 0:
        raise ValueError(f"after_calls must be >= 0, got {after_calls}")


def _resolve_target(target: str) -> Callable[..., Any]:
    module_name, _, attr = target.rpartition(".")
    if not module_name or not attr:
        raise ValueError(f"target must be a dotted callable path, got {target!r}")
    module = importlib.import_module(module_name)
    original = getattr(module, attr)
    if not callable(original):
        raise TypeError(f"target is not callable: {target!r}")
    return original


@contextmanager
def inject_fault(
    target: str,
    exc_type: Type[BaseException],
    *exc_args: Any,
    after_calls: int = 0,
) -> Generator[None, None, None]:
    """Patch target callable to raise exc_type(exc_args).

    Args:
        target: Dotted import path of the callable to patch, e.g.
                "google_kit.core.drive.fetch".
        exc_type: Exception class to raise.
        *exc_args: Positional arguments forwarded to exc_type().
        after_calls: Number of successful (pass-through) calls before faulting.
                     0 = fault on every call.

    Usage:
        with inject_fault("mymod.do_thing", ValueError, "bad value"):
            result = call_code_that_invokes_do_thing()  # raises ValueError

        with inject_fault("mymod.do_thing", TimeoutError, after_calls=2):
            # first 2 calls succeed, third raises TimeoutError
            ...
    """
    _validate_after_calls(after_calls)
    call_count: list[int] = [0]
    original_fn = _resolve_target(target)

    def _side_effect(*args: Any, **kwargs: Any) -> Any:
        call_count[0] += 1
        if call_count[0] > after_calls:
            raise exc_type(*exc_args)
        return original_fn(*args, **kwargs)

    with unittest.mock.patch(target, new=_side_effect):
        yield


@contextmanager
def inject_fault_fn(
    fn: Callable[..., Any],
    exc_type: Type[BaseException],
    *exc_args: Any,
    after_calls: int = 0,
) -> Generator[Callable[..., Any], None, None]:
    """Wrap a callable directly (no import-path patching needed).

    Yields a replacement callable that faults after `after_calls` successful
    invocations. Useful when the caller holds a direct reference.

    Args:
        fn: Original callable to wrap.
        exc_type: Exception class to raise.
        *exc_args: Arguments forwarded to exc_type().
        after_calls: Number of pass-through calls before faulting.

    Yields:
        A wrapped version of fn that faults as described.
    """
    _validate_after_calls(after_calls)
    call_count: list[int] = [0]
    original_fn = fn

    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        call_count[0] += 1
        if call_count[0] > after_calls:
            raise exc_type(*exc_args)
        return original_fn(*args, **kwargs)

    yield _wrapped
