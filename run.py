import os
import sys
import subprocess
from dotenv import load_dotenv

# Make the bundled NVIDIA cuDNN 8 / cuBLAS DLLs discoverable so faster-whisper
# can run on the GPU. ctranslate2 4.2.1 needs cuDNN 8 specifically; these dirs
# are populated by the nvidia-cudnn-cu12==8.9.7.29 / nvidia-cublas-cu12 wheels.
# The subprocess below inherits this PATH.
_nvidia = os.path.join(os.path.dirname(__file__), 'venv', 'Lib', 'site-packages', 'nvidia')
if os.path.isdir(_nvidia):
    _dll_dirs = [os.path.join(_nvidia, p, 'bin') for p in ('cudnn', 'cublas', 'cuda_nvrtc')]
    _dll_dirs = [d for d in _dll_dirs if os.path.isdir(d)]
    if _dll_dirs:
        os.environ['PATH'] = os.pathsep.join(_dll_dirs) + os.pathsep + os.environ.get('PATH', '')

print('Starting WhisperWriter...')
load_dotenv()
subprocess.run([sys.executable, os.path.join('src', 'main.py')])
