"""
Sets up a Sentry Logger

And then call `bot.load_extension('naff.ext.sentry', token=SENTRY_TOKEN)`
Optionally takes a filter function that will be called before sending the event to Sentry.
"""
import functools
import logging
from typing import Any, Callable, Optional

from naff.api.events.internal import Error
from naff.client.const import logger
from naff.models.naff.tasks.task import Task

try:
    import sentry_sdk
except ModuleNotFoundError:
    logger.error("sentry-sdk not installed, cannot enable sentry integration.  Install with `pip install naff[sentry]`")
    raise

from naff import Client, Extension, listen

__all__ = ("setup", "default_sentry_filter")


def default_sentry_filter(event: dict[str, Any], hint: dict[str, Any]) -> Optional[dict[str, Any]]:
    if "log_record" in hint:
        record: logging.LogRecord = hint["log_record"]
        if "naff" in record.name:
            #  There are some logging messages that are not worth sending to sentry.
            if ": 403" in record.message:
                return None
            if record.message.startswith("Ignoring exception in "):
                return None

    if "exc_info" in hint:
        exc_type, exc_value, tb = hint["exc_info"]
        if isinstance(exc_value, KeyboardInterrupt):
            #  We don't need to report a ctrl+c
            return None
    return event


class SentryExtension(Extension):
    @listen()
    async def on_startup(self) -> None:
        sentry_sdk.set_context(
            "bot",
            {
                "name": str(self.bot.user),
                "intents": repr(self.bot.intents),
            },
        )
        sentry_sdk.set_tag("bot_name", str(self.bot.user))

    @listen()
    async def on_error(self, event: Error) -> None:
        with sentry_sdk.configure_scope() as scope:
            scope.set_tag("source", event.source)
            if event.ctx:
                scope.set_context(
                    type(event.ctx).__name__,
                    {
                        "args": event.ctx.args,
                        "kwargs": event.ctx.kwargs,
                        "message": event.ctx.message,
                    },
                )
            sentry_sdk.capture_exception(event.error)


class HookedTask(Task):
    """We're subclassing purely for the type hinting.  The following method will be transplanted onto Task."""

    def on_error_sentry_hook(self: Task, error: Exception) -> None:
        with sentry_sdk.configure_scope() as scope:
            if isinstance(self.callback, functools.partial):
                scope.set_tag("task", self.callback.func.__name__)
            else:
                scope.set_tag("task", self.callback.__name__)

            scope.set_tag("iteration", self.iteration)
            sentry_sdk.capture_exception(error)


def setup(
    bot: Client,
    token: str = None,
    filter: Optional[Callable[[dict[str, Any], dict[str, Any]], Optional[dict[str, Any]]]] = None,
) -> None:
    if not token:
        logger.error("Cannot enable sentry integration, no token provided")
        return
    if filter is None:
        filter = default_sentry_filter
    sentry_sdk.init(token, before_send=filter)
    Task.on_error_sentry_hook = HookedTask.on_error_sentry_hook  # type: ignore
    SentryExtension(bot)
