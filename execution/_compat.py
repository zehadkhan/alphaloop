# web3.py renamed the PoA middleware across major versions:
#   v5      : web3.middleware.geth_poa_middleware  (function)
#   v6 early: web3.middleware.ExtraDataToPOAMiddleware
#   v6 late : web3.middleware.proof_of_authority.ExtraDataToPOAMiddleware
#   v7+     : web3.middleware.ExtraDataToPOAMiddleware  (re-exported)
try:
    from web3.middleware import ExtraDataToPOAMiddleware as _PoAMiddleware
except ImportError:
    try:
        from web3.middleware.proof_of_authority import ExtraDataToPOAMiddleware as _PoAMiddleware  # type: ignore[no-redef]
    except ImportError:
        from web3.middleware import geth_poa_middleware as _PoAMiddleware  # type: ignore[no-redef]

PoAMiddleware = _PoAMiddleware
