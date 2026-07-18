"""Byte-level IO that treats a local directory and an S3 bucket uniformly.

URIs are plain strings: `./data/bronze/x.csv` or `s3://bucket/bronze/x.csv`.
boto3 is imported lazily so local dev and unit tests need no AWS SDK unless
they touch s3:// paths (tests use moto).

Tabular IO (pandas/pyarrow) reads s3:// natively in Glue/Lambda; this module
only covers the byte/list/exists primitives the pipeline code needs itself.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse


def _is_s3(uri: str) -> bool:
    return uri.startswith("s3://")


def _split_s3(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    return parsed.netloc, parsed.path.lstrip("/")


def _client():
    import boto3

    return boto3.client("s3")


def read_bytes(uri: str) -> bytes:
    if _is_s3(uri):
        bucket, key = _split_s3(uri)
        return _client().get_object(Bucket=bucket, Key=key)["Body"].read()
    return Path(uri).read_bytes()


def write_bytes(uri: str, data: bytes) -> None:
    if _is_s3(uri):
        bucket, key = _split_s3(uri)
        _client().put_object(Bucket=bucket, Key=key, Body=data)
        return
    path = Path(uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)  # atomic on POSIX


def exists(uri: str) -> bool:
    if _is_s3(uri):
        bucket, key = _split_s3(uri)
        try:
            _client().head_object(Bucket=bucket, Key=key)
            return True
        except _client().exceptions.ClientError:
            return False
    return Path(uri).exists()


def list_prefix(prefix_uri: str) -> list[str]:
    """Return full URIs of objects under a prefix, sorted lexicographically.

    Landed filenames embed UTC timestamps, so sorted order == chronological
    order and the last element is always the newest object.
    """
    if _is_s3(prefix_uri):
        bucket, prefix = _split_s3(prefix_uri)
        paginator = _client().get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix.rstrip("/") + "/"):
            keys.extend(obj["Key"] for obj in page.get("Contents", []))
        return sorted(f"s3://{bucket}/{k}" for k in keys)
    root = Path(prefix_uri)
    if not root.exists():
        return []
    return sorted(str(p) for p in root.rglob("*") if p.is_file())
