"""Factory: build a BlobStorage from typed config."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .cloud_stubs import AzureBlobStorage, GCSBlobStorage, S3BlobStorage
from .interface import BlobStorage, BlobStorageError
from .local_fs import LocalFSBlobStorage

Backend = Literal["local", "s3", "azure", "gcs"]


@dataclass(frozen=True)
class BlobStorageConfig:
    backend: Backend
    local_data_dir: str | None = None
    s3_bucket: str | None = None
    s3_prefix: str = ""
    s3_region: str | None = None
    azure_account: str | None = None
    azure_container: str | None = None
    azure_prefix: str = ""
    gcs_bucket: str | None = None
    gcs_prefix: str = ""


def make_blob_storage(cfg: BlobStorageConfig) -> BlobStorage:
    if cfg.backend == "local":
        if not cfg.local_data_dir:
            raise BlobStorageError("STORAGE_BACKEND=local requires OPENINTERVIEW_DATA_DIR")
        return LocalFSBlobStorage(cfg.local_data_dir)
    if cfg.backend == "s3":
        if not cfg.s3_bucket:
            raise BlobStorageError("S3 backend requires S3_BUCKET")
        return S3BlobStorage(cfg.s3_bucket, cfg.s3_prefix, cfg.s3_region)
    if cfg.backend == "azure":
        if not (cfg.azure_account and cfg.azure_container):
            raise BlobStorageError("Azure backend requires account + container")
        return AzureBlobStorage(cfg.azure_account, cfg.azure_container, cfg.azure_prefix)
    if cfg.backend == "gcs":
        if not cfg.gcs_bucket:
            raise BlobStorageError("GCS backend requires GCS_BUCKET")
        return GCSBlobStorage(cfg.gcs_bucket, cfg.gcs_prefix)
    raise BlobStorageError(f"unknown backend: {cfg.backend}")
