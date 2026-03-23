import os
import sys
import time
import threading
import requests
from requests.auth import HTTPDigestAuth
import cv2
import numpy as np

from PyQt6 import QtCore
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QGridLayout, QFrame,
    QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap, QImage


# ---------------- PANEL BUTTON ----------------

# Custom button widget used for PTZ controls and UI buttons
class PanelButton(QWidget):
    # Custom Qt signals for interaction states
    clicked = pyqtSignal()
    pressed = pyqtSignal()
    released = pyqtSignal()

    def __init__(self, text: str, w: int = 110, h: int = 35, **kwargs):
        super().__init__()
        self.text = text                  # Button label text
        self.w = w                        # Width
        self.h = h                        # Height
        self._pressed = False             # Internal pressed state
        self.selected = False             # Optional selection state

        self.setFixedSize(self.w, self.h)  # Fix button size
        self.setCursor(Qt.CursorShape.PointingHandCursor)  # Hand cursor on hover

    # Handle mouse press events
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()                # Trigger repaint
            self.pressed.emit()          # Emit pressed signal
        super().mousePressEvent(event)

    # Handle mouse release events
    def mouseReleaseEvent(self, event):
        if self._pressed and event.button() == Qt.MouseButton.LeftButton:
            self._pressed = False
            self.update()
            self.released.emit()         # Emit released signal
            if self.rect().contains(event.pos()):
                self.clicked.emit()      # Emit clicked if still inside button
        super().mouseReleaseEvent(event)

    # Custom paint event for drawing button UI
    def paintEvent(self, event):
        from PyQt6 import QtGui, QtCore

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, False)

        rect = QtCore.QRectF(self.rect())
        lw = 1.0  # Line width
        frame_color = QtGui.QColor("#646464")

        # Simulate pressed effect by shifting drawing
        indent = 2.0 if self._pressed else 0.0
        draw_rect = rect.translated(indent, indent)

        # Background fill
        painter.setBrush(QtGui.QBrush(QtGui.QColor("#323232")))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.drawRect(draw_rect)

        # Outer border
        painter.setPen(QtGui.QPen(frame_color, lw))
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawRect(draw_rect.adjusted(lw/2, lw/2, -lw/2, -lw/2))

        # Light/shadow effect depending on pressed state
        if self._pressed:
            highlight = QtGui.QColor("#1a1a1a")
            shadow = QtGui.QColor("#6b6b6b")
        else:
            highlight = QtGui.QColor("#6b6b6b")
            shadow = QtGui.QColor("#1a1a1a")

        inner = draw_rect.adjusted(lw, lw, -lw, -lw)

        # Top/left highlight
        painter.setPen(QtGui.QPen(highlight, 1))
        painter.drawLine(inner.topLeft(), inner.topRight())
        painter.drawLine(inner.topLeft(), inner.bottomLeft())

        # Bottom/right shadow
        painter.setPen(QtGui.QPen(shadow, 1))
        painter.drawLine(inner.bottomLeft(), inner.bottomRight())
        painter.drawLine(inner.topRight(), inner.bottomRight())

        # Draw button text
        painter.setPen(QtGui.QPen(QtGui.QColor("white")))
        painter.setFont(self.font())
        painter.drawText(draw_rect.toRect(), Qt.AlignmentFlag.AlignCenter, self.text)


# ---------------- CAMERA CONFIG ----------------
# Camera connection settings (from environment variables)
CAMERA_IP = os.getenv("CAMERA_IP")
CAMERA_USER = os.getenv("CAMERA_USER")
CAMERA_PASSWORD = os.getenv("CAMERA_PASSWORD")

PTZ_SPEED = 20   # Speed for pan/tilt
ZOOM_STEP = 200  # Zoom increment

# API endpoints for PTZ control and MJPEG stream
PTZ_URL = f"http://{CAMERA_IP}/axis-cgi/com/ptz.cgi"
MJPEG_URL = f"http://{CAMERA_IP}/axis-cgi/mjpg/video.cgi"

# ---------------- FACE DETECTION ----------------
FACE_DETECT_ON = False   # Toggle for face detection
DETECT_EVERY = 5         # Run detection every N frames

# Load Haar cascade classifier for face detection
face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)

# ---------------- PTZ HELPERS ----------------
# Send PTZ command to camera
def ptz(params):
    try:
        requests.get(
            PTZ_URL,
            params=params,
            auth=HTTPDigestAuth(CAMERA_USER, CAMERA_PASSWORD),
            timeout=1
        )
    except:
        pass  # Silently ignore errors

# Move camera (pan, tilt)
def move(pan, tilt):
    ptz({"continuouspantiltmove": f"{pan},{tilt}"})

# Stop all movement
def stop():
    move(0, 0)
    ptz({"continuouszoommove": "0"})

# Zoom control
def zoom(amount):
    ptz({"continuouszoommove": str(amount)})

# ---------------- VIDEO THREAD ----------------
# Thread responsible for streaming and rendering MJPEG video
class VideoThread(threading.Thread):
    def __init__(self, label):
        super().__init__(daemon=True)
        self.label = label        # QLabel to display video
        self.last_faces = []      # Cache of last detected faces

    def run(self):
        # Connect to MJPEG stream
        r = requests.get(
            MJPEG_URL,
            stream=True,
            auth=HTTPDigestAuth(CAMERA_USER, CAMERA_PASSWORD),
            timeout=10
        )
        buffer = b""              # Buffer for incoming stream
        frame_count = 0           # Frame counter

        # Read stream in chunks
        for chunk in r.iter_content(chunk_size=4096):
            buffer += chunk
            start = buffer.find(b"\xff\xd8")  # JPEG start
            end = buffer.find(b"\xff\xd9")    # JPEG end

            # Extract full JPEG frame
            if start != -1 and end != -1:
                jpg = buffer[start:end+2]
                buffer = buffer[end+2:]

                # Decode image
                frame = cv2.imdecode(
                    np.frombuffer(jpg, np.uint8),
                    cv2.IMREAD_COLOR
                )
                if frame is None:
                    continue

                frame_count += 1

                # Face detection logic
                if FACE_DETECT_ON:
                    if frame_count % DETECT_EVERY == 0:
                        # Downscale for performance
                        small_frame = cv2.resize(frame, None, fx=0.5, fy=0.5)
                        gray = cv2.cvtColor(small_frame, cv2.COLOR_BGR2GRAY)
                        gray = cv2.equalizeHist(gray)

                        # Detect faces
                        faces = face_cascade.detectMultiScale(
                            gray,
                            scaleFactor=1.1,
                            minNeighbors=5,
                            minSize=(20, 20)
                        )

                        # Scale faces back to original size
                        scaled_faces = []
                        for (x, y, w, h) in faces:
                            scaled_faces.append((x * 2, y * 2, w * 2, h * 2))

                        self.last_faces = scaled_faces

                    # Draw rectangles around faces
                    for (x, y, w, h) in self.last_faces:
                        cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)

                # Convert to Qt image format
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = frame.shape
                img = QImage(frame.data, w, h, ch*w, QImage.Format.Format_RGB888)

                # Scale image to fit label
                pix = QPixmap.fromImage(img).scaled(
                    self.label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )

                self.label.setPixmap(pix)


# ---------------- MAIN WINDOW ----------------
# Main application window
class MainWindow(QMainWindow):
    node_status_signal = pyqtSignal(bool)  # Signal for node health status

    def __init__(self):    
        super().__init__()

        # Window setup
        self.setWindowTitle("CCTV Viewer")
        self.resize(1920, 1080)
        self.showFullScreen()

        # Theme colors
        self.BG_MAIN   = "#232323"
        self.BG_PANEL  = "#323232"
        self.BORDER    = "#444444"
        self.TEXT_MAIN = "#ffffff"
        self.TEXT_SUB  = "#B8B8B8"

        # Central widget setup
        central = QWidget()
        central.setStyleSheet(f"background-color: {self.BG_MAIN};")
        self.setCentralWidget(central)

        # Main layout
        page_layout = QVBoxLayout(central)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        # Header bar
        self.header_bar = QFrame()
        self.header_bar.setFixedHeight(90)
        self.header_bar.setStyleSheet(f"""
            QFrame {{
                background-color: {self.BG_PANEL};
            }}
        """)

        header_container_layout = QVBoxLayout(self.header_bar)
        header_container_layout.setContentsMargins(20, 0, 20, 0)
        header_container_layout.setSpacing(0)

        top_row = QHBoxLayout()

        # Logo
        logo_label = QLabel()
        pixmap = QPixmap("assets/logo.png").scaledToHeight(
            30,
            Qt.TransformationMode.SmoothTransformation
        )
        logo_label.setPixmap(pixmap)

        # Title
        title_label = QLabel("CCTV Viewer")
        title_label.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        title_label.setStyleSheet(f"color: {self.TEXT_MAIN};")

        top_row.addWidget(logo_label)
        top_row.addWidget(title_label)
        top_row.addStretch()

        # Warning banner (hidden by default)
        self.warning_label = QLabel("⚠ Node lost connection to control plane")
        self.warning_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.warning_label.setFixedHeight(40)
        self.warning_label.setStyleSheet(
            "background-color: #8b0000; color: white; font-weight: bold;"
        )
        self.warning_label.hide()

        header_container_layout.addLayout(top_row)
        header_container_layout.addWidget(self.warning_label)

        page_layout.addWidget(self.header_bar)

        content_wrapper = QWidget()
        content_layout = QVBoxLayout(content_wrapper)
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.setSpacing(20)
        page_layout.addWidget(content_wrapper)
        content_row = QHBoxLayout()
        content_row.setSpacing(20)
        content_layout.addLayout(content_row)
#--------------------------- LEFT PANEL
        self.video_panel = QFrame()
        self.video_panel.setStyleSheet(f"""
                background-color: {self.BG_PANEL};
                border-radius: 1px;
              
        """)
        self.video_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        content_row.addWidget(self.video_panel, stretch=3)
        video_layout = QVBoxLayout(self.video_panel)
        video_layout.setContentsMargins(20, 25, 20, 25)
        # Start video thread
        video_layout.setSpacing(12)
        self.video_title = QLabel("Live video (Face detect: OFF)")
        self.video_title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        self.video_title.setStyleSheet(f"color: {self.TEXT_MAIN};")
        video_layout.addWidget(self.video_title)
        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        video_layout.addWidget(self.video_label, stretch=1)
# -------------------------- RIGHT PANEL
        self.ptz_panel = QFrame()
        self.ptz_panel.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        content_row.addWidget(self.ptz_panel, alignment=Qt.AlignmentFlag.AlignTop)
        self.ptz_panel.setFixedWidth(240)   # adjust to taste
        ptz_layout = QVBoxLayout(self.ptz_panel)
        ptz_layout.setSpacing(4)
        ptz_layout.setContentsMargins(20, 20, 20, 20)
        ptz_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        ptz_title = QLabel("   ")
        ptz_title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        ptz_title.setStyleSheet(f"color: {self.TEXT_MAIN};")
        ptz_layout.addWidget(ptz_title)
        ptz_layout.addSpacing(6)
        arrow_grid = QGridLayout()
        arrow_grid.setSpacing(3)
        ptz_layout.addLayout(arrow_grid)
        
        arrow_grid.setHorizontalSpacing(3)  # control horizontal spacing specifically
        arrow_grid.setVerticalSpacing(3)
        arrow_grid.setColumnStretch(0, 0)
        arrow_grid.setColumnStretch(1, 0)
        arrow_grid.setColumnStretch(2, 0)
        arrow_grid.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_up    = PanelButton("▲", color="#323232", text_color="white", pressed_color="#323232", w=60, h=60)
        self.btn_down  = PanelButton("▼", color="#323232", text_color="white", pressed_color="#323232", w=60, h=60)
        self.btn_left  = PanelButton("◀", color="#323232", text_color="white", pressed_color="#323232", w=60, h=60)
        self.btn_right = PanelButton("▶", color="#323232", text_color="white", pressed_color="#323232", w=60, h=60)
        self.btn_stop  = PanelButton("■", color="#323232", text_color="white", pressed_color="#323232", w=60, h=60)
        
        for btn in [self.btn_up, self.btn_down, self.btn_left, self.btn_right, self.btn_stop]:
            btn.setFixedSize(60, 44)
        arrow_grid.addWidget(self.btn_up, 0, 1)
        arrow_grid.addWidget(self.btn_left, 1, 0)
        arrow_grid.addWidget(self.btn_stop, 1, 1)
        arrow_grid.addWidget(self.btn_right, 1, 2)
        arrow_grid.addWidget(self.btn_down, 2, 1)
        self.btn_up.pressed.connect(lambda: move(0, PTZ_SPEED))
        self.btn_up.released.connect(stop)
        self.btn_down.pressed.connect(lambda: move(0, -PTZ_SPEED))
        self.btn_down.released.connect(stop)
        self.btn_left.pressed.connect(lambda: move(-PTZ_SPEED, 0))
        self.btn_left.released.connect(stop)
        self.btn_right.pressed.connect(lambda: move(PTZ_SPEED, 0))
        self.btn_right.released.connect(stop)
        zoom_row = QHBoxLayout()
        ptz_layout.addLayout(zoom_row)
        self.btn_zoom_in = PanelButton("+ Zoom In")
        self.btn_zoom_out = PanelButton("- Zoom Out")
        
        self.btn_zoom_in.setFixedSize(100,40)
        self.btn_zoom_out.setFixedSize(100,40)
        self.btn_zoom_in.pressed.connect(lambda: zoom(ZOOM_STEP))
        self.btn_zoom_out.pressed.connect(lambda: zoom(-ZOOM_STEP))
        zoom_row.addWidget(self.btn_zoom_in)
        zoom_row.addWidget(self.btn_zoom_out)
        ptz_layout.addSpacing(8)
        face_panel = QFrame()
        ptz_layout.addWidget(face_panel)
        face_panel.setStyleSheet("background-color: #232323;")
        face_panel.setFrameShape(QFrame.Shape.NoFrame)
        face_layout = QVBoxLayout(face_panel)
        self.face_button = PanelButton("Toggle Face Detection")
        self.face_button.clicked.connect(self.toggle_face_detection)
        face_layout.addWidget(
            self.face_button,
            alignment=Qt.AlignmentFlag.AlignHCenter
            )
        
        self.face_button.setFixedSize(200, 40)

        # Start video thread
        self.video_thread = VideoThread(self.video_label)
        self.video_thread.start()

        # Connect node health monitoring
        self.node_status_signal.connect(self.update_ui)
        self.start_node_monitor()

    # Handle window close
    def closeEvent(self, event):
        self.client.close()  # Close client connection (if defined elsewhere)
        event.accept()

    # Start background thread to monitor node health
    def start_node_monitor(self):
        thread = threading.Thread(
            target=self.monitor_node_status,
            daemon=True
        )
        thread.start()

    # Monitor Kubernetes API health
    def monitor_node_status(self):
        api_url = "https://kubernetes.default.svc/healthz"
        ca_cert = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
        token_file = "/var/run/secrets/kubernetes.io/serviceaccount/token"

        # Read service account token once
        try:
            with open(token_file, "r") as f:
                token = f.read().strip()
            headers = {"Authorization": f"Bearer {token}"}
        except Exception as e:
            print("Failed to read service account token:", e)
            headers = {}

        # Poll API continuously
        while True:
            try:
                response = requests.get(
                    api_url,
                    headers=headers,
                    verify=ca_cert,
                    timeout=2
                )

                is_ready = (response.status_code == 200)

            except Exception:
                is_ready = False  # API unreachable

            self.node_status_signal.emit(is_ready)
            time.sleep(5)

    # Update UI based on node status
    def update_ui(self, is_ready):
        if not is_ready:
            self.warning_label.show()
        else:
            self.warning_label.hide()

    # Toggle face detection on/off
    def toggle_face_detection(self):
        global FACE_DETECT_ON
        FACE_DETECT_ON = not FACE_DETECT_ON
        state = "ON" if FACE_DETECT_ON else "OFF"
        self.video_title.setText(f"Live video (Face detect: {state})")


# ---------------- ENTRY POINT ----------------
if __name__ == "__main__":
    app = QApplication(sys.argv)  # Create Qt app
    window = MainWindow()         # Create main window
    window.show()                 # Show window
    sys.exit(app.exec())          # Start event loop