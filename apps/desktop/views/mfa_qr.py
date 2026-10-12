"""Render an authenticator QR in memory; never upload or persist its secret."""

import qrcode
from qrcode.image.pil import PilImage


def enrollment_qr(provisioning_uri):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4, box_size=1)
    qr.add_data(provisioning_uri)
    qr.make(fit=True)
    # Integer module size keeps edges sharp, including the four-module quiet zone.
    qr.box_size = max(1, 260 // (qr.modules_count + 8))
    return qr.make_image(image_factory=PilImage, fill_color="black", back_color="white").get_image().convert("RGB")
