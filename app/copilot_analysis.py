"""Run a single structured inference with the authenticated user's Copilot plan."""

import asyncio
import logging
from os import environ
from tempfile import TemporaryDirectory
from time import monotonic

from copilot import CopilotClient
from copilot.session import PermissionDecisionUserNotAvailable

SESSION_TIMEOUT = 25
ANSWER_TIMEOUT = 150
logger = logging.getLogger("uvicorn.error")


class CopilotTimeout(TimeoutError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def deny_permission(_request, _invocation):
    return PermissionDecisionUserNotAvailable()


def complete(token: str, messages: list[dict], schema: dict) -> str:
    return asyncio.run(_complete(token, messages, schema))


async def _complete(token: str, messages: list[dict], schema: dict) -> str:
    env = {key: value for key, value in environ.items() if key.upper() in {
        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "COMSPEC", "PATHEXT", "LANG",
    }}
    with TemporaryDirectory(prefix="tai-copilot-") as directory:
        client = CopilotClient(github_token=token, use_logged_in_user=False, mode="empty",
                               env=env, working_directory=directory, base_directory=directory)
        started_at = monotonic()
        phase = "runtime"

        def track(event):
            nonlocal phase
            stage = {"user.message": "queued", "model.call_start": "generating",
                     "model.call_finished": "model_finished", "assistant.message": "answer_received",
                     "session.error": "upstream_error", "session.idle": "session_idle"}.get(event.type.value)
            if stage and not event.agent_id:
                phase = stage
                logger.info("Copilot phase=%s elapsed=%.1fs", phase, monotonic() - started_at)

        try:
            try:
                async with asyncio.timeout(SESSION_TIMEOUT):
                    await client.start()
                    phase = "session_setup"
                    session = await client.create_session(
                        model="auto", available_tools=[], on_permission_request=deny_permission,
                        system_message={"mode": "replace", "content": messages[0]["content"]},
                        working_directory=directory, enable_config_discovery=False,
                        enable_session_store=False, skip_custom_instructions=True,
                    )
            except TimeoutError as error:
                raise CopilotTimeout("copilot_session_timeout") from error

            phase = "dispatch"
            logger.info("Copilot session ready elapsed=%.1fs input_bytes=%d", monotonic() - started_at,
                        len(messages[1]["content"].encode()))
            unsubscribe = session.on(track)
            try:
                event = await session.send_and_wait(messages[1]["content"], response_schema=schema,
                                                    timeout=ANSWER_TIMEOUT)
            except TimeoutError as error:
                reason = ("copilot_completion_timeout" if phase in {"model_finished", "answer_received", "session_idle"}
                          else "copilot_answer_timeout")
                raise CopilotTimeout(reason) from error
            finally:
                unsubscribe()
            logger.info("Copilot completed elapsed=%.1fs", monotonic() - started_at)
        except Exception as error:
            logger.warning("Copilot failed phase=%s elapsed=%.1fs error_type=%s", phase, monotonic() - started_at,
                           type(error).__name__)
            raise
        finally:
            await client.force_stop()
    return event.data.content if event is not None else ""
