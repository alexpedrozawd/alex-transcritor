#!/usr/bin/env python3
"""Configura uma instalação do Alex Transcritor para usar o servidor privado."""

import argparse
import getpass
import ipaddress
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://100.84.64.122:8300")
    parser.add_argument(
        "--token-stdin",
        action="store_true",
        help="lê o token da entrada padrão (adequado para um pipe SSH)",
    )
    args = parser.parse_args()
    url = args.url.rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise SystemExit("URL do servidor inválida.")
    if parsed.scheme == "http":
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            raise SystemExit("HTTP sem TLS exige um IP Tailscale.") from None
        if address not in ipaddress.ip_network("100.64.0.0/10"):
            raise SystemExit("HTTP sem TLS exige um IP Tailscale.")
    token_source = sys.stdin.readline() if args.token_stdin else getpass.getpass(
        "Token do servidor: "
    )
    token = token_source.strip()
    if len(token) < 32:
        raise SystemExit("Token inválido: esperado ao menos 32 caracteres.")

    config_dir = Path.home() / ".config" / "alex-transcritor"
    config_file = config_dir / "config.json"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_dir.chmod(0o700)
    try:
        data = json.loads(config_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data.update(
        transcription_backend="remote",
        remote_url=url,
        remote_token=token,
    )
    fd, temp_name = tempfile.mkstemp(dir=config_dir, prefix=".config-remote-", suffix=".tmp")
    temp = Path(temp_name)
    os.fchmod(fd, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(data, output, indent=2, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, config_file)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    print(f"Cliente configurado para {url}")


if __name__ == "__main__":
    main()
