"""Check if all dependencies and setup are correct."""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def check_imports():
    """Check if all required packages are installed."""
    print("Checking dependencies...")
    
    required_packages = {
        "cv2": "opencv-python",
        "numpy": "numpy",
        "pydantic": "pydantic",
        "pydantic_settings": "pydantic-settings",
        "pytz": "pytz",
        "ultralytics": "ultralytics",
        "apscheduler": "APScheduler",
        "requests": "requests",
    }
    
    missing = []
    for module, package in required_packages.items():
        try:
            __import__(module)
            print(f"[OK] {package}")
        except ImportError:
            print(f"[FAIL] {package} - MISSING")
            missing.append(package)
    
    # Optional packages
    print("\nOptional dependencies:")
    optional_packages = {
        "deep_sort_realtime": "deep-sort-realtime (for DeepSORT tracker)",
    }
    
    for module, package in optional_packages.items():
        try:
            __import__(module)
            print(f"[OK] {package}")
        except ImportError:
            print(f"[SKIP] {package} - Not installed (optional)")
    
    if missing:
        print(f"\n[ERROR] Missing packages: {', '.join(missing)}")
        print("Install with: pip install -r requirements.txt")
        return False
    
    print("\n[OK] All required packages installed")
    return True


def check_config():
    """Check if configuration file exists."""
    print("\nChecking configuration...")
    
    config_files = [".env", "config.yaml"]
    found = False
    
    for config_file in config_files:
        if Path(config_file).exists():
            print(f"[OK] Found {config_file}")
            found = True
        else:
            print(f"[SKIP] {config_file} not found")
    
    if not found:
        print("[WARNING] No configuration file found. Copy env.example to .env and configure it.")
        print("  Or create config.yaml based on config.yaml.example")
    
    return found


def check_yolo_model():
    """Check if YOLO model can be loaded."""
    print("\nChecking YOLO model...")
    
    try:
        from ultralytics import YOLO
        # Try to load a small model
        model = YOLO("yolov8n.pt")
        print("[OK] YOLO model loaded successfully")
        return True
    except Exception as e:
        print(f"[FAIL] Failed to load YOLO model: {e}")
        print("  Note: Model will be downloaded automatically on first use")
        return False


def check_tracker():
    """Check if tracker can be initialized."""
    print("\nChecking tracker...")
    
    try:
        from app.tracker import Tracker
        tracker = Tracker(tracker_type="bytetrack")
        print("[OK] ByteTrack tracker initialized")
        return True
    except Exception as e:
        print(f"[FAIL] Failed to initialize tracker: {e}")
        return False


def main():
    """Run all checks."""
    print("=" * 50)
    print("People Counter MVP - Setup Check")
    print("=" * 50)
    
    all_ok = True
    
    # Check imports
    if not check_imports():
        all_ok = False
    
    # Check config
    check_config()
    
    # Check YOLO
    if not check_yolo_model():
        all_ok = False
    
    # Check tracker
    if not check_tracker():
        all_ok = False
    
    print("\n" + "=" * 50)
    if all_ok:
        print("[SUCCESS] Setup check passed!")
        print("\nYou can now run the application with:")
        print("  python scripts/run.py")
    else:
        print("[WARNING] Setup check found issues. Please fix them before running.")
    print("=" * 50)


if __name__ == "__main__":
    main()

