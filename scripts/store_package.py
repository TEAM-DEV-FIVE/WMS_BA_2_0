"""Stage a verified desktop bundle for MSIX; Store identity is supplied by its owner."""

import argparse
import json
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from apps.desktop.bundle import verify_manifest

NS = {
    "": "http://schemas.microsoft.com/appx/manifest/foundation/windows10",
    "uap": "http://schemas.microsoft.com/appx/manifest/uap/windows10",
    "rescap": "http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities",
    "desktop6": "http://schemas.microsoft.com/appx/manifest/desktop/windows10/6",
}
TEST_IDENTITY = {
    "name": "InternTechLead.WMS.PackagingTest",
    "publisher": "CN=WMS Packaging Test Only",
    "publisher_display_name": "WMS Packaging Test Only",
    "display_name": "WMS Packaging Test Only",
}


def validate_identity(identity, version, test_only=False):
    if set(identity) != {"name", "publisher", "publisher_display_name", "display_name"}:
        raise ValueError("Three Partner Center identity fields and reserved display_name required")
    if not all(isinstance(value, str) and value.strip() == value for value in identity.values()):
        raise ValueError("Invalid identity text")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{2,49}", identity["name"]):
        raise ValueError("Invalid package identity name")
    if not identity["publisher"].startswith("CN=") or len(identity["publisher"]) < 4:
        raise ValueError("Partner Center Publisher required")
    if not 1 <= len(identity["publisher_display_name"]) <= 256:
        raise ValueError("PublisherDisplayName required")
    display_name = identity["display_name"]
    if not 1 <= len(display_name) <= 256 or any(ord(char) < 32 for char in display_name):
        raise ValueError("Reserved display_name must be nonempty text without control characters")
    if not re.fullmatch(r"\d+\.\d+\.\d+\.0", version):
        raise ValueError("Store version must have four parts and final part 0")
    if any(int(part) > 65535 for part in version.split(".")) or int(version.split(".")[0]) == 0:
        raise ValueError("Store major version must be positive; components <= 65535")
    if not test_only and any("test only" in value.lower() or "packagingtest" in value.lower()
                             or "<" in value or ">" in value for value in identity.values()):
        raise ValueError("Placeholder/test identity cannot be a Store submission")


def manifest(identity, version):
    for prefix, uri in NS.items():
        ET.register_namespace(prefix, uri)

    def add(parent, name, attributes=None, text=None):
        prefix, local = name.split(":") if ":" in name else ("", name)
        node = ET.SubElement(parent, f"{{{NS[prefix]}}}{local}", attributes or {})
        node.text = text
        return node

    root = ET.Element(f"{{{NS['']}}}Package", {"IgnorableNamespaces": "uap rescap desktop6"})
    add(root, "Identity", {"Name": identity["name"], "Publisher": identity["publisher"],
                           "Version": version, "ProcessorArchitecture": "x64"})
    properties = add(root, "Properties")
    add(properties, "DisplayName", text=identity["display_name"])
    add(properties, "PublisherDisplayName", text=identity["publisher_display_name"])
    add(properties, "Logo", text="Assets/StoreLogo.png")
    # Keep the existing journal/cache outside package-managed state on uninstall.
    add(properties, "desktop6:FileSystemWriteVirtualization", text="disabled")
    dependencies = add(root, "Dependencies")
    add(dependencies, "TargetDeviceFamily", {"Name": "Windows.Desktop", "MinVersion": "10.0.19041.0",
                                              "MaxVersionTested": "10.0.19041.0"})
    resources = add(root, "Resources")
    add(resources, "Resource", {"Language": "vi-VN"})
    add(resources, "Resource", {"Language": "en-US"})
    apps = add(root, "Applications")
    app = add(apps, "Application", {"Id": "WMS", "Executable": "App/WMS.exe",
                                    "EntryPoint": "Windows.FullTrustApplication"})
    add(app, "uap:VisualElements", {"DisplayName": identity["display_name"],
        "Description": "Quản lý kho qua WMS API trên mạng LAN", "BackgroundColor": "#161b22",
        "Square150x150Logo": "Assets/Square150x150Logo.png",
        "Square44x44Logo": "Assets/Square44x44Logo.png"})
    capabilities = add(root, "Capabilities")
    add(capabilities, "rescap:Capability", {"Name": "runFullTrust"})
    add(capabilities, "rescap:Capability", {"Name": "unvirtualizedResources"})
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def stage(bundle, output, identity, version, test_only=False):
    validate_identity(identity, version, test_only)
    record = verify_manifest(bundle)
    paths = list(bundle.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise ValueError("Links are not allowed in Store input")
    actual = {p.relative_to(bundle).as_posix() for p in paths if p.is_file()}
    if actual != set(record["files"]) | {"manifest.json"}:
        raise ValueError("Store input contains unmanifested files")
    if output.exists() or output.resolve().is_relative_to(bundle.resolve()):
        raise ValueError("Use a new staging directory outside the bundle")
    output.mkdir(parents=True)
    shutil.copytree(bundle, output / "App")
    (output / "AppxManifest.xml").write_bytes(manifest(identity, version))
    assets = output / "Assets"
    assets.mkdir()
    font_path = Path(__file__).resolve().parents[1] / "apps/server/printing_assets/DejaVuSans.ttf"
    for filename, size in (("StoreLogo.png", 50), ("Square44x44Logo.png", 44), ("Square150x150Logo.png", 150)):
        with Image.new("RGBA", (size, size), "#161b22") as image:
            draw = ImageDraw.Draw(image)
            font = ImageFont.truetype(str(font_path), max(10, size // 3))
            draw.text((size / 2, size / 2), "WMS", font=font, fill="white", anchor="mm")
            image.save(assets / filename)
    return {"status": "TEST_PACKAGE_ONLY" if test_only else "AWAITING_STORE_SUBMISSION",
            "identity": identity, "package_version": version, "runtime_version": record["version"],
            "runtime_commit": record["commit"], "store_signed": False, "store_certified": False,
            "installed_package_test": "NOT_RUN", "bundle_files_verified": len(record["files"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--identity", type=Path)
    parser.add_argument("--version", default="1.0.1.0")
    parser.add_argument("--test-identity", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    options = parser.parse_args()
    if bool(options.identity) == options.test_identity:
        parser.error("Supply a Partner Center identity JSON OR explicit --test-identity")
    identity = TEST_IDENTITY if options.test_identity else json.loads(options.identity.read_text(encoding="utf-8-sig"))
    result = stage(options.bundle, options.stage, identity, options.version, options.test_identity)
    options.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
