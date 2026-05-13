import sys
import os

# Wichtig: Projekt-Root zum Python-Path hinzufügen
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from client.main import main
import asyncio

if __name__ == "__main__":
    print("🚀 MeshCompute Client wird gestartet...")
    asyncio.run(main())
