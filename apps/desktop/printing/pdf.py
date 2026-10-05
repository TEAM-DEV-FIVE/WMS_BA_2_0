"""All PDFium lifetime operations are protected: PDFium is not thread safe."""

from threading import RLock

LOCK = RLock()


def page_image(data, index=0, scale=1.1):
    import pypdfium2 as pdfium

    with LOCK, pdfium.PdfDocument(data) as document:
        if len(document) > 200 or not 0 <= index < len(document):
            raise ValueError("PDF page limit")
        page = document[index]
        bitmap = page.render(scale=scale)
        try:
            return bitmap.to_pil().copy(), len(document)
        finally:
            bitmap.close()
            page.close()
