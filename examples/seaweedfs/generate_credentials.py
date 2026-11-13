#!/usr/bin/env python3
"""Generate private SeaweedFS JSON and AWS shared files outside this repository.

Never prints credentials. Files are created exclusively with mode 0600.
"""
import argparse
import configparser
import json
import os
from pathlib import Path
import secrets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="new private directory outside the checkout")
    args = parser.parse_args()
    directory = args.directory.expanduser().resolve()
    checkout = Path(__file__).resolve().parents[2]
    if directory == checkout or checkout in directory.parents:
        parser.error("credential directory must be outside the checkout")
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    access_key = secrets.token_hex(10).upper()
    secret_key = secrets.token_urlsafe(40)
    config = {"identities": [{"name": "lab-admin", "credentials": [
        {"accessKey": access_key, "secretKey": secret_key}],
        "actions": ["Admin", "Read", "Write", "List", "Tagging"]}]}
    contents = {"seaweedfs_s3_config": json.dumps(config) + "\n"}
    credentials = configparser.ConfigParser()
    credentials["seaweedfs-lab"] = {"aws_access_key_id": access_key,
                                   "aws_secret_access_key": secret_key}
    from io import StringIO
    out = StringIO()
    credentials.write(out)
    contents["credentials"] = out.getvalue()
    contents["config"] = ("[profile seaweedfs-lab]\nregion = us-east-1\n"
                          "s3 =\n    addressing_style = path\n    signature_version = s3v4\n")
    for name, content in contents.items():
        fd = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
    print("Private configuration created; no credentials printed.")


if __name__ == "__main__":
    main()
