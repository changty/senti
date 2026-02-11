"""Docker sandbox executor with security constraints."""

from __future__ import annotations

import io
import json
import logging
import tarfile
from typing import Any

import docker
from docker.errors import ContainerError, ImageNotFound, APIError

from senti.exceptions import SandboxError, SandboxTimeoutError

logger = logging.getLogger(__name__)

# Default container limits
DEFAULT_MEM_LIMIT = "128m"
DEFAULT_CPU_QUOTA = 50000  # 50% of one core
DEFAULT_TIMEOUT = 30  # seconds


class SandboxExecutor:
    """Runs skill code in isolated Docker containers.

    Contract: JSON passed via SENTI_INPUT env var → container runs run.py → JSON on stdout.
    """

    def __init__(self) -> None:
        self._client = docker.from_env()
        self._ensured_networks: set[str] = set()

    async def run(
        self,
        image: str,
        input_data: dict[str, Any],
        *,
        network_mode: str = "none",
        timeout: int = DEFAULT_TIMEOUT,
        mem_limit: str = DEFAULT_MEM_LIMIT,
        environment: dict[str, str] | None = None,
        upload_file: tuple[str, bytes] | None = None,
    ) -> str:
        """Run a skill in a sandboxed container and return the result string.

        The container receives JSON on stdin and must write JSON to stdout.
        If upload_file is provided as (filename, data), the file is injected
        into the container at /data/upload/<filename> via put_archive before
        the container starts.
        """
        import asyncio

        return await asyncio.get_event_loop().run_in_executor(
            None,
            self._run_sync,
            image,
            input_data,
            network_mode,
            timeout,
            mem_limit,
            environment,
            upload_file,
        )

    def _ensure_network(self, name: str) -> None:
        """Create a Docker network if it doesn't already exist."""
        if name == "none" or name in self._ensured_networks:
            return
        try:
            self._client.networks.get(name)
        except docker.errors.NotFound:
            self._client.networks.create(name, driver="bridge")
            logger.info("Created Docker network: %s", name)
        self._ensured_networks.add(name)

    @staticmethod
    def _make_tar(filename: str, data: bytes) -> bytes:
        """Create an in-memory tar archive containing a single file."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            info = tarfile.TarInfo(name=filename)
            info.size = len(data)
            info.mode = 0o444
            tar.addfile(info, io.BytesIO(data))
        return buf.getvalue()

    def _run_sync(
        self,
        image: str,
        input_data: dict[str, Any],
        network_mode: str,
        timeout: int,
        mem_limit: str,
        environment: dict[str, str] | None,
        upload_file: tuple[str, bytes] | None = None,
    ) -> str:
        """Synchronous container execution."""
        self._ensure_network(network_mode)
        container = None

        # Pass input via environment variable instead of stdin
        env = dict(environment or {})
        env["SENTI_INPUT"] = json.dumps(input_data)

        # When uploading a file:
        #  - read_only must be False so put_archive can write to the image layer
        #  - Do NOT put /data/upload on tmpfs — tmpfs would shadow the put_archive write
        has_upload = upload_file is not None

        try:
            container = self._client.containers.create(
                image=image,
                detach=True,
                network_mode=network_mode,
                read_only=not has_upload,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                mem_limit=mem_limit,
                cpu_quota=DEFAULT_CPU_QUOTA,
                user="nobody",
                tmpfs={"/tmp": "size=10m,noexec"},
                environment=env,
            )

            # Inject file into container's writable layer before starting
            if upload_file:
                filename, data = upload_file
                tar_data = self._make_tar(filename, data)
                container.put_archive("/data/upload", tar_data)
                logger.info("Injected %s (%d bytes) into container /data/upload/", filename, len(data))

            container.start()

            # Wait for completion
            result = container.wait(timeout=timeout)
            exit_code = result.get("StatusCode", -1)

            stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
            stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")

            if exit_code != 0:
                logger.error("Sandbox container exited %d: %s", exit_code, stderr[:500])
                raise SandboxError(f"Container exited with code {exit_code}: {stderr[:200]}")

            # Parse JSON output
            try:
                output = json.loads(stdout)
                return output.get("result", stdout.strip())
            except json.JSONDecodeError:
                return stdout.strip()

        except docker.errors.ContainerError as exc:
            raise SandboxError(f"Container error: {exc}") from exc
        except ImageNotFound:
            raise SandboxError(f"Sandbox image not found: {image}")
        except APIError as exc:
            if "timeout" in str(exc).lower():
                raise SandboxTimeoutError(f"Container timed out after {timeout}s")
            raise SandboxError(f"Docker API error: {exc}") from exc
        except SandboxError:
            raise
        except Exception as exc:
            raise SandboxError(f"Sandbox execution failed: {exc}") from exc
        finally:
            if container:
                try:
                    container.remove(force=True)
                except Exception:
                    logger.warning("Failed to remove container %s", container.id[:12])
