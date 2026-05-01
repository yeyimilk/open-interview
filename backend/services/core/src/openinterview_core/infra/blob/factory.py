from __future__ import annotations

from openinterview_storage import BlobStorage, BlobStorageConfig, make_blob_storage

from ...config import Settings


def build_blob_storage(s: Settings) -> BlobStorage:
    cfg = BlobStorageConfig(
        backend=s.storage_backend,
        local_data_dir=s.openinterview_data_dir,
        s3_bucket=s.s3_bucket,
        s3_prefix=s.s3_prefix,
        s3_region=s.s3_region,
        azure_account=s.azure_storage_account,
        azure_container=s.azure_storage_container,
        azure_prefix=s.azure_storage_prefix,
        gcs_bucket=s.gcs_bucket,
        gcs_prefix=s.gcs_prefix,
    )
    return make_blob_storage(cfg)
