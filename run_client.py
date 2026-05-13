import sys
import os
from pathlib import Path
import asyncio

# Projekt-Root zum Python-Path hinzufügen
root = Path(__file__).parent.absolute()
sys.path.insert(0, str(root))

from client.main import main

if __name__ == "__main__":
    asyncio.run(main())
