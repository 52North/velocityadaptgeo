from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError


class RasterPansharpeningProcessor(BaseProcessor):
    """OGC API - Processes stub: multi-resolution raster pansharpening & pyramid generation"""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "raster-pansharpening",
            "title": (
                "Multi-Resolution Pansharpening, Radiometric Harmonisation and "
                "Overview Pyramid Generation"
            ),
            "description": (
                "Fuses a high-resolution panchromatic band with a "
                "lower-resolution multispectral image using a "
                "component-substitution or multi-resolution-analysis "
                "pansharpening algorithm, harmonises radiometry against a "
                "reference reflectance profile, and materialises a "
                "cloud-optimised, power-of-two overview pyramid of the fused "
                "product."
            ),
            "keywords": [
                "pansharpening",
                "remote-sensing",
                "raster-fusion",
                "radiometric-harmonisation",
                "cloud-optimised-geotiff",
            ],
            "inputs": {
                "panchromaticBand": {
                    "title": "High-resolution panchromatic band reference (COG URI)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "multispectralBands": {
                    "title": "Lower-resolution multispectral band stack reference (COG URI)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "pansharpeningMethod": {
                    "title": "Fusion algorithm ('Brovey', 'Gram-Schmidt', 'wavelet-MRA')",
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
                    "title": "Pansharpened, radiometrically-harmonised image with generated overview pyramid",
                    "schema": {"type": "object"},
                },
                "qualityMetrics": {
                    "title": "Per-band spectral and spatial fusion-quality metrics (e.g. ERGAS, SAM)",
                    "schema": {"type": "object"},
                },
            },
        }

        super().__init__(processor_def, process_metadata)

    def execute(self, data, outputs=None):
        raise ProcessorExecuteError(
            "raster-pansharpening is a metadata-only stub and has no execution backend yet"
        )
