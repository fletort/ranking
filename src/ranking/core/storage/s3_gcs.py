from botocore.client import Config

from .s3 import S3StorageProvider


class GcsS3StorageProvider(S3StorageProvider):
    """StorageProvider backed by Google Cloud Storage (GCS) using the S3 API."""

    def _build_client_kwargs(self) -> dict:
        kwargs = super()._build_client_kwargs()
        if kwargs.get("endpoint_url") is None:
            kwargs["endpoint_url"] = "https://storage.googleapis.com"

        kwargs["config"] = Config(
            signature_version="s3v4",
            s3={
                "addressing_style": "path",
            },
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        )
        return kwargs
