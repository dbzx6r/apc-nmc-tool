"""
main.py — Entry point for APC NMC Field Tool.
"""

import sys
import os

# When running as a PyInstaller .exe, ensure the bundle dir is on the path.
if getattr(sys, "frozen", False):
    os.chdir(os.path.dirname(sys.executable))

from gui.main_window import APCToolApp


def main():
    app = APCToolApp()
    app.mainloop()


if __name__ == "__main__":
    main()
