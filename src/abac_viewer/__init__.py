from importlib.metadata import PackageNotFoundError, version

try:
    # Stamped into the app artifact by scripts/build-viewer.sh, which ships the
    # packages as source rather than as an installed distribution.
    from ._version import version as __version__
except ImportError:
    try:
        __version__ = version("uc-declarative-abac")
    except PackageNotFoundError:
        __version__ = "unknown"
