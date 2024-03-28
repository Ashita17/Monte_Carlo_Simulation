

if str == bytes:
    from pyopt import Exposer
    from pyopt import PrintHelp
    from pyopt import PyoptError
    from pyopt import __doc__
else:
    # py3k
    from .pyopt import Exposer
    from .pyopt import PrintHelp
    from .pyopt import PyoptError
    from .pyopt import __doc__

