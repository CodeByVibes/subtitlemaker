"""CUDA library setup for CTranslate2."""

import os
import sys


def reexec_with_cuda_libs():
    """Re-exec once with the pip nvidia-* libs on LD_LIBRARY_PATH.

    CTranslate2 needs CUDA 12 libs (cuBLAS/cuDNN) from the pip nvidia-*
    packages. The loader reads LD_LIBRARY_PATH only at process start.
    """

    if sys.platform.startswith("linux") and not os.environ.get("_CUDA_REEXEC"):
        try:
            import nvidia.cublas.lib
            import nvidia.cudnn.lib

            _libs = [list(m.__path__)[0] for m in (nvidia.cublas.lib, nvidia.cudnn.lib)]
            os.environ["LD_LIBRARY_PATH"] = ":".join(
                _libs + [p for p in [os.environ.get("LD_LIBRARY_PATH")] if p]
            )
            os.environ["_CUDA_REEXEC"] = "1"
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except ImportError:
            pass
