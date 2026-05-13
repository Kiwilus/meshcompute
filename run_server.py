import sys
import os

# Projekt-Root zum Python-Path hinzufügen
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server.main import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main())
