"""Site-specific JSON-RPC services for site entry flows."""

from .e3951 import dispatch as dispatch_e3951
from .febet import dispatch as dispatch_febet
from .gk881 import dispatch as dispatch_gk881


SITE_ENTRY_SERVICES = {
    "e3951.openDG": dispatch_e3951,
    "febet.openDG": dispatch_febet,
    "gk881.openDG": dispatch_gk881,
}
