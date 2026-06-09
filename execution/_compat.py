# web3.py PoA middleware across major versions (async variant for AsyncWeb3):
#   v6 (this install): web3.middleware.async_geth_poa_middleware
#   v7+              : web3.middleware.ExtraDataToPOAMiddleware (async-aware)
try:
    from web3.middleware import ExtraDataToPOAMiddleware as PoAMiddleware
except ImportError:
    try:
        from web3.middleware.proof_of_authority import ExtraDataToPOAMiddleware as PoAMiddleware  # type: ignore[no-redef]
    except ImportError:
        try:
            from web3.middleware import async_geth_poa_middleware as PoAMiddleware  # type: ignore[no-redef]
        except ImportError:
            from web3.middleware import geth_poa_middleware as PoAMiddleware  # type: ignore[no-redef]
