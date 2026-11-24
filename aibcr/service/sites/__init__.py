"""Site-specific JSON-RPC services for site entry flows."""

from .ae888 import dispatch as dispatch_ae888
from .e3951 import dispatch as dispatch_e3951
from .febet import dispatch as dispatch_febet
from .gk881 import (dispatch_open as dispatch_gk881,
                    dispatch_session_clear as dispatch_gk881_session_clear,
                    dispatch_session_info as dispatch_gk881_session_info)
from .vnwtop import dispatch as dispatch_vnwtop


SITE_ENTRY_SERVICES = {
    "888ae66.openDG": dispatch_ae888,
    "e3951.openDG": dispatch_e3951,
    "febet.openDG": dispatch_febet,
    "gk881.openDG": dispatch_gk881,
    "gk881.sessionInfo": dispatch_gk881_session_info,
    "gk881.sessionClear": dispatch_gk881_session_clear,
    "vnwtop.openDG": dispatch_vnwtop,
}
