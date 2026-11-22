"""Universal PaperLab bundle format and merger. See README.md."""
from .bundle import (BundleError, FORMAT, SUFFIX, VERSION, build_bundle, inspect_bundle,  # noqa: F401
                     merge_bundle, open_bundle)
