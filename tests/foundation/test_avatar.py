import base64
from io import BytesIO

import pytest
from PIL import Image, PngImagePlugin
from pydantic import ValidationError

from packages.contracts.identity import ProfileUpdate
from packages.media.avatar import MAX_FILE_BYTES, load_avatar_file, normalize_avatar, validate_avatar


def photo(color="red", fmt="PNG", size=(400, 200)):
    output = BytesIO()
    Image.new("RGB", size, color).save(output, format=fmt)
    return output.getvalue()


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_avatar_is_bounded_square_png_and_repeatable(fmt, tmp_path):
    raw = photo(fmt=fmt)
    encoded = normalize_avatar(raw)
    assert validate_avatar(encoded) == encoded
    with Image.open(BytesIO(base64.b64decode(encoded))) as image:
        assert image.format == "PNG" and image.size == (256, 256)
        assert not image.getexif()
    path = tmp_path / "avatar"
    path.write_bytes(raw)
    assert load_avatar_file(str(path)) == encoded


def test_avatar_drops_metadata_and_rejects_untrusted_files():
    output = BytesIO()
    meta = PngImagePlugin.PngInfo()
    meta.add_text("Location", "private location")
    Image.new("RGB", (10, 10)).save(output, "PNG", pnginfo=meta)
    clean = base64.b64decode(normalize_avatar(output.getvalue()))
    assert b"private location" not in clean
    for invalid in (b"<svg></svg>", b"not an image", b"x"*(MAX_FILE_BYTES+1), photo(fmt="GIF")):
        with pytest.raises(ValueError):
            normalize_avatar(invalid)
    for invalid in ("bad base64 !", "a"*350001, base64.b64encode(b"not png").decode()):
        with pytest.raises(ValueError):
            validate_avatar(invalid)
    with pytest.raises(ValueError):
        normalize_avatar(photo(size=(5000, 4001)))


def test_avatar_checks_orientation_and_rejects_animation():
    image = Image.new("RGB", (20, 10), "red")
    image.paste("blue", (10, 0, 20, 10))
    exif = Image.Exif()
    exif[274] = 6
    output = BytesIO()
    image.save(output, "JPEG", exif=exif)
    with Image.open(BytesIO(base64.b64decode(normalize_avatar(output.getvalue())))) as result:
        assert result.getpixel((128, 0))[0] > 200
        assert result.getpixel((128, 255))[2] > 200
    output = BytesIO()
    image.save(output, "PNG", save_all=True, append_images=[Image.new("RGB", (20, 10), "green")])
    with pytest.raises(ValueError):
        normalize_avatar(output.getvalue())


def test_avatar_contract_distinguishes_untouched_and_removed():
    args = dict(display_name="Name", expected_display_name="Name")
    assert "avatar_base64" not in ProfileUpdate(**args).model_fields_set
    with pytest.raises(ValidationError):
        ProfileUpdate(**args, avatar_base64=None)
    assert "avatar_base64" in ProfileUpdate(**args, avatar_base64=None, expected_avatar_version=0).model_fields_set


@pytest.mark.integration
def test_avatar_upload_persistence_isolation_retry_remove_and_conflict(iam):
    _, secret = iam.user(mfa=True)
    _, other_secret = iam.user("other", mfa=True)
    headers = iam.headers(iam.login(secret=secret))
    route = "/api/v1/auth/profile"
    body = dict(display_name="operator", expected_display_name="operator", avatar_base64=normalize_avatar(photo()), expected_avatar_version=0)
    for _ in range(2):
        response = iam.client.patch(route, headers=headers, json=body)
        assert response.status_code == 200, response.text
        assert response.json()["avatar_version"] == 1
        assert response.json()["avatar_base64"] == body["avatar_base64"]
    assert iam.client.get("/api/v1/auth/me", headers=headers).json()["avatar_base64"] == body["avatar_base64"]
    other = iam.headers(iam.login("other", other_secret))
    assert iam.client.get("/api/v1/auth/me", headers=other).json()["avatar_base64"] is None
    invalid = iam.client.patch(route, headers=headers, json={**body, "display_name": "Must not save", "avatar_base64": "not an image"})
    assert invalid.status_code == 422
    assert iam.client.get("/api/v1/auth/me", headers=headers).json()["display_name"] == "operator"
    stale = iam.client.patch(route, headers=headers, json={**body, "avatar_base64": normalize_avatar(photo("blue"))})
    assert stale.status_code == 409 and stale.json()["code"] == "STALE_VERSION"
    name_only = iam.client.patch(route, headers=headers, json={"display_name": "New name", "expected_display_name": "operator"})
    assert name_only.json()["avatar_base64"] == body["avatar_base64"]
    remove = iam.client.patch(route, headers=headers, json={**body, "display_name": "New name", "expected_display_name": "New name", "avatar_base64": None, "expected_avatar_version": 1})
    assert remove.status_code == 200
    assert remove.json()["avatar_base64"] is None and remove.json()["avatar_version"] == 2


def test_image_failure_does_not_sign_out(tmp_path):
    from types import SimpleNamespace

    from apps.desktop.presenters.session import SessionPresenter

    invalid = tmp_path / "broken.png"
    invalid.write_bytes(b"not an image")
    api = SimpleNamespace(session_generation=0, in_session=lambda generation, fn: fn())
    presenter = SessionPresenter(None, api)
    try:
        result = presenter.guarded_run(0, "avatar_preview", [str(invalid)])
        assert result.message and not result.signed_out
        assert result.data is None
    finally:
        presenter.close()
    with pytest.raises(ValueError):
        load_avatar_file(str(tmp_path))
