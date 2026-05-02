import os
import sys
from pathlib import Path

# Offscreen rendering — deve ser definido antes de qualquer import PyQt6
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Garante que o pacote alex_transcritor seja encontrado a partir da raiz do projeto
sys.path.insert(0, str(Path(__file__).parent.parent))
