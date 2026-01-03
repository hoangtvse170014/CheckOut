"""Test camera connection and display stream."""

import sys
import cv2
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import load_config
from app.camera import CameraStream


def main():
    """Test camera stream."""
    config = load_config()
    
    print(f"Testing camera: {config.camera.url}")
    print("Press 'q' to quit")
    
    camera = CameraStream(
        url=config.camera.url,
        reconnect_delay=config.camera.reconnect_delay,
        max_reconnect_attempts=config.camera.max_reconnect_attempts,
        fps_cap=config.camera.fps_cap,
    )
    
    if not camera.connect():
        print("Failed to connect to camera")
        return
    
    try:
        while True:
            success, frame = camera.read()
            if not success or frame is None:
                continue
            
            # Display FPS
            fps = camera.get_fps()
            cv2.putText(
                frame,
                f"FPS: {fps:.1f}",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 255, 0),
                2,
            )
            
            cv2.imshow("Camera Test", frame)
            
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
                
    except KeyboardInterrupt:
        print("\nInterrupted")
    finally:
        camera.release()
        cv2.destroyAllWindows()
        print("Camera released")


if __name__ == "__main__":
    main()

