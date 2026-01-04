"""
Dependency Checker - Verifies all required tools are installed
Run this before first use to ensure everything is set up correctly.
"""

import subprocess
import sys
import shutil


def check_python():
    """Check Python version"""
    version = sys.version_info
    print(f"Python: {version.major}.{version.minor}.{version.micro}", end=" ")
    
    if version.major >= 3 and version.minor >= 11:
        print("✓")
        return True
    else:
        print("✗ (need 3.11+)")
        return False


def check_spotdl():
    """Check spotDL installation"""
    print("spotDL: ", end="")
    
    try:
        result = subprocess.run(
            ["spotdl", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            version = result.stdout.strip() or result.stderr.strip()
            print(f"{version} ✓")
            return True
        else:
            print("✗ (installed but not working)")
            return False
    except FileNotFoundError:
        print("✗ (not installed)")
        print("  → Install with: pip install spotdl")
        return False
    except Exception as e:
        print(f"✗ (error: {e})")
        return False


def check_ffmpeg():
    """Check FFmpeg installation"""
    print("FFmpeg: ", end="")
    
    # First check if it's in PATH
    if shutil.which("ffmpeg"):
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                # Extract version from first line
                first_line = result.stdout.split("\n")[0]
                print(f"{first_line[:50]}... ✓")
                return True
        except Exception:
            pass
    
    print("✗ (not installed or not in PATH)")
    print("  → Windows: choco install ffmpeg")
    print("  → Or download from: https://ffmpeg.org/download.html")
    return False


def check_tkinter():
    """Check Tkinter availability"""
    print("Tkinter: ", end="")
    
    try:
        import tkinter
        print(f"{tkinter.TkVersion} ✓")
        return True
    except ImportError:
        print("✗ (not installed)")
        print("  → Usually included with Python on Windows")
        return False


def main():
    print("=" * 50)
    print("Swim Sync - Dependency Check")
    print("=" * 50)
    print()
    
    results = []
    
    results.append(("Python 3.11+", check_python()))
    results.append(("spotDL", check_spotdl()))
    results.append(("FFmpeg", check_ffmpeg()))
    results.append(("Tkinter", check_tkinter()))
    
    print()
    print("-" * 50)
    
    all_ok = all(r[1] for r in results)
    
    if all_ok:
        print("✓ All dependencies satisfied!")
        print("  Run 'python app.py' to start Swim Sync")
    else:
        print("✗ Some dependencies are missing")
        print("  Please install the missing items listed above")
    
    print()
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
