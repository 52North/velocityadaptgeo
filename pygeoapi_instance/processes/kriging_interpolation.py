from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError


class KrigingInterpolationProcessor(BaseProcessor):
    """OGC API - Processes stub: Bayesian spatiotemporal kriging interpolation"""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "bayesian-spatiotemporal-kriging",
            "title": "Bayesian Spatiotemporal Kriging Interpolation for Sparse Sensor Networks",
            "description": (
                "Fits a hierarchical Bayesian variogram model jointly across space "
                "and time to interpolate a continuous field (e.g. air quality, soil "
                "moisture) from irregularly-sampled, gap-afflicted sensor "
                "observations, returning posterior mean and credible-interval "
                "surfaces at arbitrary query geometries and timestamps."
            ),
            "keywords": [
                "interpolation",
                "kriging",
                "bayesian",
                "spatiotemporal",
                "geostatistics",
                "sensor-network",
                "uncertainty-quantification",
            ],
            "inputs": {
                "observations": {
                    "title": "Sensor observation collection (GeoJSON FeatureCollection with timestamp + value properties)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "queryGeometry": {
                    "title": "Geometry defining the interpolation domain (Point, LineString, Polygon or Grid)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "targetTimestamps": {
                    "title": "ISO-8601 timestamps at which the posterior field should be evaluated",
                    "schema": {"type": "array"},
                    "required": True,
                },
                "variogramModel": {
                    "title": (
                        "Prior covariance family for the spatiotemporal variogram "
                        "(e.g. 'separable-exponential', 'product-sum-matern')"
                    ),
                    "schema": {"type": "string"},
                    "required": False,
                },
                "credibleInterval": {
                    "title": "Width of the posterior credible interval to report (e.g. 0.95)",
                    "schema": {"type": "number"},
                    "required": False,
                },
            },
            "outputs": {
                "posteriorMean": {
                    "title": "Interpolated posterior mean field",
                    "schema": {"type": "object"},
                },
                "posteriorUncertainty": {
                    "title": "Per-cell credible-interval bounds of the posterior field",
                    "schema": {"type": "object"},
                },
            },
        }

        super().__init__(processor_def, process_metadata)

    def execute(self, data, outputs=None):
        raise ProcessorExecuteError(
            "bayesian-spatiotemporal-kriging is a metadata-only stub and has no execution backend yet"
        )
