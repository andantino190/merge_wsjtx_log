#!/usr/bin/env python3
"""Remote synchronization and backup module using SSH/SCP and local file operations."""

import datetime
import os
import shlex
import shutil
import subprocess
from typing import Optional, Tuple


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

    def _scp_remote_path(self) -> str:
        """Returns remote path specification for scp command."""
        # For scp, paths with spaces work reliably when quoted inside the arg: host:'/path with spaces'
        return f"{self.host}:'{self.path}'"

    def fetch(self, local_dest: str) -> float:
        """Fetches the file from remote or local to local_dest.

        Returns file mtime.
        """
        if self.is_remote:
            scp_arg = self._scp_remote_path()
            cmd = ["scp", "-p", scp_arg, local_dest]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode != 0:
                # If scp fails, attempt ssh cat as fallback
                cat_cmd = ["ssh", self.host, f"cat {self._remote_quoted_path()}"]
                with open(local_dest, "wb") as f:
                    cat_res = subprocess.run(cat_cmd, stdout=f, stderr=subprocess.PIPE)
                if cat_res.returncode != 0:
                    err_msg = res.stderr.strip() or cat_res.stderr.decode("utf-8", errors="replace").strip()
                    raise RuntimeError(f"Failed to fetch {self.raw}: {err_msg}")
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
            res = subprocess.run(["ssh", self.host, remote_cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode != 0:
                raise RuntimeError(f"Failed to create remote backup on {self.host}: {res.stderr.strip()}")
        else:
            if os.path.exists(self.path):
                shutil.copy2(self.path, backup_path)

        return backup_path

    def deploy(self, local_src: str) -> None:
        """Atomically replaces the target file with local_src."""
        if self.is_remote:
            tmp_remote_path = f"{self.path}.tmp_{os.getpid()}"
            scp_dest = f"{self.host}:'{tmp_remote_path}'"

            # 1. Upload to remote temporary file
            res = subprocess.run(["scp", "-p", local_src, scp_dest], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode != 0:
                raise RuntimeError(f"Failed to upload temporary file to {self.host}: {res.stderr.strip()}")

            # 2. Atomic rename on remote
            quoted_tmp = shlex.quote(tmp_remote_path)
            quoted_dest = self._remote_quoted_path()
            rename_cmd = f"mv {quoted_tmp} {quoted_dest}"
            res_rename = subprocess.run(["ssh", self.host, rename_cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res_rename.returncode != 0:
                raise RuntimeError(f"Failed to replace target file on {self.host}: {res_rename.stderr.strip()}")
        else:
            dest_dir = os.path.dirname(self.path)
            if dest_dir:
                os.makedirs(dest_dir, exist_ok=True)
            tmp_local = f"{self.path}.tmp_{os.getpid()}"
            shutil.copy2(local_src, tmp_local)
            os.replace(tmp_local, self.path)
