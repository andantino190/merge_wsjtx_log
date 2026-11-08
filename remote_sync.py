#!/usr/bin/env python3
"""Remote synchronization and backup module using SSH and local file operations."""

import datetime
import os
import shlex
import shutil
import subprocess
from typing import Optional


class LogTarget:
    """Represents a log target, either local or remote (host:path)."""

    def __init__(self, target_str: str):
        self.raw = target_str.strip()
        if not self.raw.startswith("/") and ":" in self.raw:
            self.host, self.path = self.raw.split(":", 1)
            self.is_remote = True
        else:
            self.host = ""
            self.path = self.raw
            self.is_remote = False

    def __str__(self) -> str:
        return self.raw

    def _remote_quoted_path(self) -> str:
        """Returns single-quoted path safe for remote shells."""
        return shlex.quote(self.path)

    def fetch(self, local_dest: str) -> float:
        """Fetches the file from remote or local to local_dest.

        Returns file mtime.
        """
        if self.is_remote:
            quoted_path = self._remote_quoted_path()
            # Fetch file content via ssh cat
            cat_cmd = ["ssh", self.host, f"cat {quoted_path}"]
            with open(local_dest, "wb") as f:
                res = subprocess.run(cat_cmd, stdout=f, stderr=subprocess.PIPE)
            if res.returncode != 0:
                err_msg = res.stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"Failed to fetch {self.raw}: {err_msg}")

            # Fetch remote mtime via stat (supports Linux -c %Y and macOS -f %m)
            stat_cmd = [
                "ssh",
                self.host,
                f"stat -f %m {quoted_path} 2>/dev/null || stat -c %Y {quoted_path} 2>/dev/null",
            ]
            stat_res = subprocess.run(stat_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            output = stat_res.stdout.strip()
            if stat_res.returncode == 0 and output.isdigit():
                remote_mtime = float(output)
                os.utime(local_dest, (remote_mtime, remote_mtime))
            else:
                remote_mtime = os.path.getmtime(local_dest)
            return remote_mtime
        else:
            if not os.path.isfile(self.path):
                raise FileNotFoundError(f"Local file not found: {self.path}")
            shutil.copy2(self.path, local_dest)
            return os.path.getmtime(local_dest)

    def create_backup(self, timestamp_str: Optional[str] = None) -> str:
        """Creates a backup of the original file on the target host/directory.

        Returns the backup file path.
        """
        if not timestamp_str:
            timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{self.path}.bak_{timestamp_str}"

        if self.is_remote:
            quoted_src = self._remote_quoted_path()
            quoted_bak = shlex.quote(backup_path)
            # Check existence and cp -p
            remote_cmd = f"[ -f {quoted_src} ] && cp -p {quoted_src} {quoted_bak}"
            res = subprocess.run(
                ["ssh", self.host, remote_cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if res.returncode != 0:
                raise RuntimeError(
                    f"Failed to create remote backup on {self.host}: {res.stderr.strip()}"
                )
        else:
            if os.path.exists(self.path):
                shutil.copy2(self.path, backup_path)

        return backup_path

    def deploy(self, local_src: str) -> None:
        """Atomically replaces the target file with local_src."""
        if self.is_remote:
            tmp_remote_path = f"{self.path}.tmp_{os.getpid()}"
            quoted_tmp = shlex.quote(tmp_remote_path)
            quoted_dest = self._remote_quoted_path()

            # 1. Upload to remote temporary file via ssh stdin pipe
            with open(local_src, "rb") as f:
                upload_cmd = ["ssh", self.host, f"cat > {quoted_tmp}"]
                res_upload = subprocess.run(
                    upload_cmd,
                    stdin=f,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            if res_upload.returncode != 0:
                raise RuntimeError(
                    f"Failed to upload temporary file to {self.host}: {res_upload.stderr.strip()}"
                )

            # 2. Atomic rename on remote
            rename_cmd = f"mv {quoted_tmp} {quoted_dest}"
            res_rename = subprocess.run(
                ["ssh", self.host, rename_cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if res_rename.returncode != 0:
                raise RuntimeError(
                    f"Failed to replace target file on {self.host}: {res_rename.stderr.strip()}"
                )
        else:
            dest_dir = os.path.dirname(self.path)
            if dest_dir:
                os.makedirs(dest_dir, exist_ok=True)
            tmp_local = f"{self.path}.tmp_{os.getpid()}"
            shutil.copy2(local_src, tmp_local)
            os.replace(tmp_local, self.path)
