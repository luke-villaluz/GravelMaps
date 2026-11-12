"""GravelMaps: a route planner that favors dirt, gravel and unpaved roads."""

# The app's version. A release is cut by tagging the same version, e.g. v0.2.0 (see RELEASING.md).
__version__ = "0.3.1"

REPO = "luke-villaluz/GravelMaps"

# Sent with every outside request, so the services we use can tell who is calling.
USER_AGENT = f"GravelMaps/{__version__} (+https://github.com/{REPO})"
