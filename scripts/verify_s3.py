#!/usr/bin/env python3
"""Signed, path-style PUT/GET/DELETE smoke test using the AWS credential chain.

Creates only a uniquely named test object; --create-bucket may create the bucket.
Never deletes the bucket, prints credentials, or prints SDK exception bodies.
"""
import argparse
import os
import sys
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=os.environ.get("S3_ENDPOINT"))
    parser.add_argument("--bucket", default="lab")
    parser.add_argument("--create-bucket", action="store_true")
    args = parser.parse_args()
    if not args.endpoint or not args.endpoint.startswith(("http://", "https://")):
        parser.error("set --endpoint or S3_ENDPOINT to an HTTP(S) S3 endpoint")
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError

    s3 = boto3.client("s3", endpoint_url=args.endpoint, region_name="us-east-1",
                      config=Config(signature_version="s3v4",
                                    s3={"addressing_style": "path"},
                                    connect_timeout=10, read_timeout=30,
                                    retries={"max_attempts": 2, "mode": "standard"}))
    if args.create_bucket:
        try:
            s3.head_bucket(Bucket=args.bucket)
        except ClientError as exc:
            if str(exc.response.get("Error", {}).get("Code")) not in ("404", "NoSuchBucket", "NotFound"):
                raise
            # us-east-1: omit LocationConstraint.
            s3.create_bucket(Bucket=args.bucket)
    s3.head_bucket(Bucket=args.bucket)
    key = "small-lab-verification/" + uuid.uuid4().hex
    payload = b"SeaweedFS small-lab signed object verification\n" + os.urandom(64)
    try:
        s3.put_object(Bucket=args.bucket, Key=key, Body=payload)
        print("PUT: PASS")
        result = s3.get_object(Bucket=args.bucket, Key=key)
        try:
            actual = result["Body"].read()
        finally:
            result["Body"].close()
        if actual != payload:
            raise RuntimeError("object bytes differ")
        print("GET and byte comparison: PASS")
    finally:
        # Safe to retry deletion even if PUT timed out after committing.
        s3.delete_object(Bucket=args.bucket, Key=key)
    try:
        s3.head_object(Bucket=args.bucket, Key=key)
    except ClientError as exc:
        if str(exc.response.get("Error", {}).get("Code")) not in ("404", "NoSuchKey", "NotFound"):
            raise
    else:
        raise RuntimeError("object remains after DELETE")
    print("DELETE and subsequent HEAD not-found: PASS")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # SDK/network exception text can include endpoint/configuration details.
        print(f"S3 verification failed ({type(exc).__name__}); check connectivity, credentials, and server health privately.", file=sys.stderr)
        sys.exit(1)
