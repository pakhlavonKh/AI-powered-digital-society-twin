"""SocietyTwin research workbench package.

Layers follow docs/architecture.md: population, sampling and evaluation never
import web frameworks or model SDKs; only ``societytwin.agents`` starts the
external MatrAIx runtime, and it does so in isolated subprocesses.
"""

SYNTHETIC_POPULATION_LABEL = (
    "Synthetic population generated from official aggregate statistics (sources listed). Not a census."
)
SYNTHETIC_RESPONSE_LABEL = (
    "Synthetic personas and AI-generated responses. Not real people. Not a prediction of real behaviour."
)
FIXTURE_ATTRIBUTION_NOTE = (
    "Source attribution is as recorded by the project; the original raw TÜİK files are not in this "
    "checkout, so raw-source verification is unavailable."
)

__version__ = "0.1.0"
