from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError


class RasterPansharpeningProcessor(BaseProcessor):
    """OGC API - Processes stub: multi-resolution raster pansharpening & pyramid generation"""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "raster-pansharpening",
            "title": "Pansharpening of Satellite Imagery",
            "description": (
                "Sharpens a lower-resolution multispectral satellite image with a "
                "high-resolution panchromatic band (pansharpening or image fusion), using "
                "Brovey, Gram-Schmidt or wavelet methods, and harmonises its radiometry "
                "against a reference reflectance profile. The result keeps the "
                "panchromatic band's pixel size and CRS and is written as a "
                "cloud-optimised GeoTIFF with overviews. Also returns per-band "
                "fusion-quality metrics. Produces sharper colour imagery - for example to "
                "map buildings or tree crowns."
            ),
            "keywords": [
                "pansharpening",
                "image-fusion",
                "remote-sensing",
                "satellite-imagery",
                "radiometric-harmonisation",
                "cloud-optimised-geotiff",
            ],
            "inputs": {
                "panchromaticBand": {
                    "title": "High-resolution panchromatic band (COG URI)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "multispectralBands": {
                    "title": "Lower-resolution multispectral band stack (COG URI)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "pansharpeningMethod": {
                    "title": "Fusion method, e.g. 'Brovey', 'Gram-Schmidt' or 'wavelet-MRA'",
                    "schema": {"type": "string"},
                    "required": False,
                },
                "referenceReflectanceProfile": {
                    "title": "Reference reflectance profile used for radiometric harmonisation",
                    "schema": {"type": "object"},
                    "required": False,
                },
            },
            "outputs": {
                "fusedImage": {
                    "title": "Pansharpened image with overviews (cloud-optimised GeoTIFF)",
                    "schema": {"type": "object"},
                },
                "qualityMetrics": {
                    "title": "Per-band spectral and spatial fusion-quality metrics (e.g. ERGAS, SAM)",
                    "schema": {"type": "object"},
                },
            },
            "example": {
                "inputs": {
                    "panchromaticBand": {"href": "https://example.org/pan.tif"},
                    "multispectralBands": {"href": "https://example.org/ms.tif"},
                }
            },
        }

        super().__init__(processor_def, process_metadata)

    def execute(self, data, outputs=None):
        raise ProcessorExecuteError(
            "raster-pansharpening is a metadata-only stub and has no execution backend yet"
        )
