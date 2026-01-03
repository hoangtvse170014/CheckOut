"""Demo with video file instead of live camera."""

import sys
import cv2
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import load_config
from app.detector import PersonDetector
from app.tracker import Tracker
from app.line_counter import LineCounter


def draw_overlay(frame, line_counter, tracks, fps):
    """Draw overlay on frame."""
    overlay = frame.copy()
    
    # Draw line
    line_start, line_end = line_counter.get_line_points()
    cv2.line(overlay, line_start, line_end, (0, 255, 0), 2)
    cv2.circle(overlay, line_start, 5, (0, 255, 0), -1)
    cv2.circle(overlay, line_end, 5, (0, 255, 0), -1)
    
    # Draw tracks
    for track_id, x1, y1, x2, y2, conf in tracks:
        # Draw bounding box
        cv2.rectangle(overlay, (int(x1), int(y1)), (int(x2), int(y2)), (255, 0, 0), 2)
        
        # Draw track ID
        cv2.putText(
            overlay,
            f"ID:{track_id}",
            (int(x1), int(y1) - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 0, 0),
            2,
        )
        
        # Draw centroid
        centroid_x = int((x1 + x2) / 2)
        centroid_y = int((y1 + y2) / 2)
        cv2.circle(overlay, (centroid_x, centroid_y), 5, (0, 0, 255), -1)
    
    # Draw counts
    count_in, count_out = line_counter.get_counts()
    cv2.putText(
        overlay,
        f"IN: {count_in} | OUT: {count_out} | FPS: {fps:.1f}",
        (10, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 255, 0),
        2,
    )
    
    return overlay


def main():
    """Run demo with video file."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Demo people counter with video file")
    parser.add_argument("video_path", help="Path to video file")
    parser.add_argument("--fps", type=int, default=10, help="Processing FPS")
    args = parser.parse_args()
    
    config = load_config()
    
    print(f"Loading video: {args.video_path}")
    
    # Open video
    cap = cv2.VideoCapture(args.video_path)
    if not cap.isOpened():
        print(f"Failed to open video: {args.video_path}")
        return
    
    # Get video properties
    fps_video = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Video: {width}x{height} @ {fps_video} FPS")
    
    # Initialize components
    detector = PersonDetector(
        model_name=config.detection.model_name,
        conf_threshold=config.detection.conf_threshold,
        iou_threshold=config.detection.iou_threshold,
        device=config.detection.device,
    )
    
    tracker = Tracker(
        tracker_type=config.tracking.tracker_type,
        track_thresh=config.tracking.track_thresh,
        track_buffer=config.tracking.track_buffer,
        match_thresh=config.tracking.match_thresh,
    )
    
    line_counter = LineCounter(
        line_start=config.line.line_start,
        line_end=config.line.line_end,
        min_track_length=config.line.min_track_length,
        cooldown_frames=config.line.cooldown_frames,
    )
    
    frame_count = 0
    start_time = time.time()
    last_frame_time = start_time
    min_interval = 1.0 / args.fps
    
    print("Press 'q' to quit, 'r' to reset counts")
    
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("End of video")
                break
            
            # FPS capping
            current_time = time.time()
            if current_time - last_frame_time < min_interval:
                continue
            last_frame_time = current_time
            
            frame_count += 1
            
            # Detect
            detections = detector.detect(frame)
            
            # Track
            tracks = tracker.update(detections, frame)
            
            # Count
            crossings = line_counter.update(tracks)
            
            if crossings:
                for track_id, direction in crossings:
                    print(f"Frame {frame_count}: Track {track_id} crossed {direction.upper()}")
            
            # Draw overlay
            elapsed = time.time() - start_time
            fps_actual = frame_count / elapsed if elapsed > 0 else 0
            overlay = draw_overlay(frame, line_counter, tracks, fps_actual)
            
            cv2.imshow("People Counter Demo", overlay)
            
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('r'):
                line_counter.reset_counts()
                print("Counts reset")
    
    except KeyboardInterrupt:
        print("\nInterrupted")
    finally:
        cap.release()
        cv2.destroyAllWindows()
        
        count_in, count_out = line_counter.get_counts()
        print(f"\nFinal counts: IN={count_in}, OUT={count_out}")
        print(f"Total frames processed: {frame_count}")


if __name__ == "__main__":
    main()

