from types import SimpleNamespace

from Models import FileAssetStatus
from storage.manager import StorageManager


class PresignClientStub:
    def __init__(self):
        self.calls = []

    def generate_presigned_url(self, *, ClientMethod, Params, ExpiresIn):
        self.calls.append(
            {
                "ClientMethod": ClientMethod,
                "Params": Params,
                "ExpiresIn": ExpiresIn,
            }
        )
        return "https://storage.example.test/signed-url"


def test_download_urls_do_not_override_content_disposition():
    asset = SimpleNamespace(
        id=99,
        bucket="test-bucket",
        storage_key="companies/1/assets/99/original",
        content_type="image/jpeg",
        status=FileAssetStatus.READY.value,
    )
    user = SimpleNamespace(id=1, company_id=1)

    manager = StorageManager.__new__(StorageManager)
    manager.presign_client = PresignClientStub()
    manager._get_asset_or_404 = lambda asset_id: asset
    manager._check_company_access = lambda asset, user: None

    for disposition in ("attachment", "inline"):
        url = manager.create_download_url(
            asset_id=asset.id,
            user=user,
            disposition=disposition,
            expires_seconds=300,
        )
        assert url == "https://storage.example.test/signed-url"

    assert len(manager.presign_client.calls) == 2

    for call in manager.presign_client.calls:
        assert call["ClientMethod"] == "get_object"
        assert call["ExpiresIn"] == 300
        assert call["Params"] == {
            "Bucket": "test-bucket",
            "Key": "companies/1/assets/99/original",
            "ResponseContentType": "image/jpeg",
        }
        assert "ResponseContentDisposition" not in call["Params"]
