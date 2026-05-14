#!/usr/bin/env python3
# builder/build_exe.py
import sys, shutil, subprocess, os
from pathlib import Path

def build(bot_id: str):
    builder_dir = Path(__file__).resolve().parent
    config_file = builder_dir / "bot_configs" / f"config_{bot_id}.py"
    if not config_file.exists():
        print(f"❌ Konfiguration für '{bot_id}' nicht gefunden. Bitte generate_secrets.py ausführen.")
        sys.exit(1)

    # Konfiguration als config.py in den client-Ordner kopieren
    target_config = builder_dir.parent / "client" / "config.py"
    shutil.copy(config_file, target_config)
    print(f"[+] config_{bot_id}.py → client/config.py")

    # PyInstaller aufrufen
    os.chdir(builder_dir.parent)
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", f"meshbot_{bot_id}",
        "--add-data", f"client/config.py:.",
        "client/main.py"
    ]
    print(f"[+] Starte PyInstaller: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    print(f"[✓] EXE erstellt: dist/meshbot_{bot_id}.exe")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Verwendung: python build_exe.py <bot_id>")
        sys.exit(1)
    build(sys.argv[1])