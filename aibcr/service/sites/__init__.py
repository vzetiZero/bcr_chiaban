"""Site-specific JSON-RPC services for site entry flows."""

from .febet import dispatch as dispatch_febet
from .gk881 import dispatch as dispatch_gk881


SITE_ENTRY_SERVICES = {
    "febet.openDG": dispatch_febet,
    "gk881.openDG": dispatch_gk881,
}

