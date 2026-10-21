from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError


class KrigingInterpolationProcessor(BaseProcessor):
    """OGC API - Processes stub: Bayesian spatiotemporal kriging interpolation"""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "bayesian-spatiotemporal-kriging",
            "title": "Spatiotemporal Kriging of Sparse Sensor Readings",
            "description": (
                "Interpolates a continuous field such as air quality or soil moisture "
                "from scattered, gappy sensor readings (spatiotemporal or Bayesian "
                "kriging), fitting a variogram jointly across space and time. Distances "
                "are measured in metres in a local UTM projection. Returns the estimated "
                "mean field at the query geometry and timestamps, with credible-interval "
                "bounds on it. Fills the gaps between monitoring stations - for example "
                "estimating hourly air pollution across a city from a handful of sensors."
            ),
            "keywords": [
                "interpolation",
                "kriging",
                "spatial-interpolation",
                "bayesian",
                "spatiotemporal",
                "geostatistics",
                "sensor-network",
                "uncertainty-quantification",
                "air-quality",
            ],
            "inputs": {
                "observations": {
                    "title": "Sensor readings with timestamp and value properties (GeoJSON FeatureCollection, EPSG:4326)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "queryGeometry": {
                    "title": "Points, line or area to evaluate the field at (GeoJSON, EPSG:4326)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "targetTimestamps": {
                    "title": "ISO-8601 timestamps to evaluate the field at",
                    "schema": {"type": "array", "items": {"type": "string"}},
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
                    "title": "Width of the credible interval to report, e.g. 0.95",
                    "schema": {"type": "number"},
                    "required": False,
                },
            },
            "outputs": {
                "posteriorMean": {
                    "title": "Interpolated mean field at the query geometry and timestamps",
                    "schema": {"type": "object"},
                },
                "posteriorUncertainty": {
                    "title": "Lower and upper credible-interval bounds of the field",
                    "schema": {"type": "object"},
                },
            },
            "example": {
                "inputs": {
                    "observations": {"type": "FeatureCollection", "features": []},
                    "queryGeometry": {"type": "Point", "coordinates": [7.6261, 51.9607]},
                    "targetTimestamps": ["2026-07-01T14:00:00Z"],
                }
            },
        }

        super().__init__(processor_def, process_metadata)

    def execute(self, data, outputs=None):
        raise ProcessorExecuteError(
            "bayesian-spatiotemporal-kriging is a metadata-only stub and has no execution backend yet"
        )
