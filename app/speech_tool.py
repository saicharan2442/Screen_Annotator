"""Speech-to-Text tool: real-time live typing via Vosk.

Clicking on the screen activates the microphone. As you speak, text appears
in real-time on the screen exactly where you clicked.
"""

import json
import logging
import queue
import threading

import sounddevice as sd
from . import windows_api
from PySide6.QtCore import QObject, Signal, QTimer
from vosk import Model, KaldiRecognizer

from .annotations import TextAnnotation
from .drawing import refresh_text_bbox

log = logging.getLogger(__name__)

# Single global instance so we don't load the 40MB model repeatedly
_vosk_model = None

def get_vosk_model():
    global _vosk_model
    if _vosk_model is None:
        log.info("Loading Vosk model (will download if missing)...")
        _vosk_model = Model(model_name="vosk-model-small-en-us-0.15")
    return _vosk_model


class SpeechStreamWorker(QObject):
    """Runs a real-time Vosk recognizer and emits partial/final transcripts."""
    partial_result = Signal(str)
    final_chunk = Signal(str)
    finished = Signal(str, bool)

    def __init__(self):
        super().__init__()
        self.cancelled = False
        self.audio_queue = queue.Queue()

    def run(self):
        try:
            model = get_vosk_model()
            recognizer = KaldiRecognizer(model, 16000)

            def callback(indata, frames, time, status):
                if status:
                    log.warning("Audio status: %s", status)
                self.audio_queue.put(bytes(indata))

            with sd.RawInputStream(samplerate=16000, blocksize=8000, dtype='int16',
                                   channels=1, callback=callback):
                log.info("Speech recognition started listening...")
                final_text = ""
                
                while not self.cancelled:
                    try:
                        data = self.audio_queue.get(timeout=0.2)
                    except queue.Empty:
                        continue
                        
                    if recognizer.AcceptWaveform(data):
                        res = json.loads(recognizer.Result())
                        text = res.get("text", "")
                        if text:
                            self.final_chunk.emit(text + " ")
                    else:
                        res = json.loads(recognizer.PartialResult())
                        partial = res.get("partial", "")
                        # Always emit partial, even if empty, so the UI can clear the previous partial
                        self.partial_result.emit(partial)

                # Get the last chunk of text after stream stops
                res = json.loads(recognizer.FinalResult())
                text = res.get("text", "")
                if text:
                    self.final_chunk.emit(text + " ")
                    
                self.finished.emit("", True)

        except Exception as e:
            log.exception("Speech recognition stream failed")
            self.finished.emit(f"Error: {e}", False)


class SpeechTool(QObject):
    """Click anywhere on the overlay to place a real-time speech annotation."""

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.active_annotation = None
        self.worker = None
        self.thread = None
        self._is_listening = False
        
        # Text editing state
        self._base_text = ""
        self._partial_speech = ""
        self._cursor_pos = 0
        self._shift_down = False
        
        # Caret blinking
        self._caret_on = False
        self._caret_timer = QTimer()
        self._caret_timer.timeout.connect(self._blink)

    def _blink(self):
        if not self._is_listening:
            return
        self._caret_on = not self._caret_on
        region = self.caret_region()
        if region:
            self.controller.refresh(region)

    @property
    def caret_visible(self):
        return self._is_listening and self._caret_on

    @property
    def ann(self):
        return self.active_annotation

    def caret_region(self):
        if not self.active_annotation:
            return None
        from .drawing import get_caret_info, text_metrics, text_font
        from PySide6.QtGui import QFontMetricsF
        
        pos = self._cursor_pos
        cx_offset, line_idx = get_caret_info(self.active_annotation, pos)
        
        _, _, line_h, _ = text_metrics(self.active_annotation)
        fm = QFontMetricsF(text_font(self.active_annotation))
        
        cx = self.active_annotation.x + cx_offset
        y = self.active_annotation.y + line_idx * line_h
        return (cx - 1, y, cx + 3, y + fm.height())

    def on_activate(self):
        self._hook = windows_api.KeyboardHook(self._on_key)
        self._hook.start()

    def on_deactivate(self):
        if hasattr(self, '_hook') and self._hook:
            self._hook.stop()
        self.cancel_session()

    def on_press(self, gx, gy):
        if self._is_listening:
            # Click to finalize
            self.finalize_session()
            return

        hit = self.controller.store.hit_topmost(gx, gy)
        if isinstance(hit, TextAnnotation):
            self.begin_session(gx, gy, existing_ann=hit)
        else:
            self.begin_session(gx, gy)

    def on_move(self, gx, gy):
        pass

    def on_release(self, gx, gy):
        pass

    def begin_session(self, gx, gy, existing_ann=None):
        self.cancel_session()

        if existing_ann:
            self.active_annotation = existing_ann
            self._base_text = existing_ann.text
            self._cursor_pos = len(self._base_text)
            self.controller.store.bring_forward(self.active_annotation)
        else:
            cfg = self.controller.settings.section("text")
            self.active_annotation = TextAnnotation(
                x=gx, y=gy, text="",
                font_family=cfg.get("family", "Segoe UI"),
                size=int(cfg.get("size", 28)),
                bold=bool(cfg.get("bold", True)),
                color=cfg.get("color", "#FFFFFF"),
                opacity=float(cfg.get("opacity", 1.0)),
            )
            self._base_text = ""
            self._cursor_pos = 0
            self.controller.store.add(self.active_annotation)
        
        refresh_text_bbox(self.active_annotation)
        self.controller.refresh(self.active_annotation.bbox())

        self._is_listening = True
        self._caret_on = True
        self._caret_timer.start(500)
        self._partial_speech = ""
        self._shift_down = False
        
        self.worker = SpeechStreamWorker()
        self.worker.partial_result.connect(self._on_partial_result)
        self.worker.final_chunk.connect(self._on_final_chunk)
        self.worker.finished.connect(self._on_worker_finished)
        
        self.thread = threading.Thread(target=self.worker.run, daemon=True)
        self.thread.start()

    def _refresh_text(self):
        if not self.active_annotation:
            return
        old_bbox = self.active_annotation.bbox()
        
        # Merge base text and partial speech at the cursor
        before = self._base_text[:self._cursor_pos]
        after = self._base_text[self._cursor_pos:]
        
        self.active_annotation.text = before + self._partial_speech + after
        refresh_text_bbox(self.active_annotation)
        new_bbox = self.active_annotation.bbox()
        self.controller.refresh(self._combined_bbox(old_bbox, new_bbox))

    def _on_partial_result(self, text):
        if not self._is_listening or not self.active_annotation:
            return
        self._partial_speech = text
        self._refresh_text()

    def _on_final_chunk(self, text):
        if not self._is_listening or not self.active_annotation:
            return
        self._partial_speech = ""
        self._insert(text)

    def _insert(self, text):
        if not self.active_annotation:
            return
        before = self._base_text[:self._cursor_pos]
        after = self._base_text[self._cursor_pos:]
        self._base_text = before + text + after
        self._cursor_pos += len(text)
        self._refresh_text()

    def _backspace(self):
        if self._cursor_pos > 0:
            before = self._base_text[:self._cursor_pos - 1]
            after = self._base_text[self._cursor_pos:]
            self._base_text = before + after
            self._cursor_pos -= 1
            self._refresh_text()

    def _paste(self):
        from PySide6.QtWidgets import QApplication
        cb = QApplication.clipboard()
        if cb.ownsClipboard() or cb.text():
            self._insert(cb.text())

    def _on_key(self, vk, scan, is_down):
        """Low-level hook callback. Return True to swallow the key."""
        if not self._is_listening:
            return False
            
        if vk == 0x14:  # VK_CAPITAL (Caps Lock)
            return False
            
        if vk in (windows_api.VK_SHIFT, 0xA0, 0xA1):
            self._shift_down = is_down
            return True
            
        if not is_down:
            return True

        ctrl = windows_api.is_ctrl_down()

        if vk == windows_api.VK_ESCAPE:
            self.finalize_session()
            return True
        if vk == windows_api.VK_RETURN:
            if ctrl:
                self.finalize_session()
            else:
                self._insert("\n")
            return True
        if vk == windows_api.VK_BACK:
            self._backspace()
            return True
            
        # Arrow keys
        if vk == 0x25:  # Left
            if self._cursor_pos > 0:
                self._cursor_pos -= 1
                self._refresh_text()
            return True
        if vk == 0x27:  # Right
            if self._cursor_pos < len(self._base_text):
                self._cursor_pos += 1
                self._refresh_text()
            return True
        if vk == 0x26:  # Up (simulate left for now)
            if self._cursor_pos > 0:
                self._cursor_pos = max(0, self._cursor_pos - 10)
                self._refresh_text()
            return True
        if vk == 0x28:  # Down (simulate right for now)
            if self._cursor_pos < len(self._base_text):
                self._cursor_pos = min(len(self._base_text), self._cursor_pos + 10)
                self._refresh_text()
            return True

        if ctrl and vk == ord("V"):
            self._paste()
            return True
        if vk in (windows_api.VK_SHIFT, windows_api.VK_CONTROL,
                  windows_api.VK_MENU, 0xA2, 0xA3, 0xA4, 0xA5):
            return True
        if ctrl:
            return True

        char = windows_api.vk_to_char(vk, scan, self._shift_down)
        if char and all(ord(c) >= 32 for c in char):
            self._insert(char)
        return True

    def finalize_session(self):
        if self.worker:
            self.worker.cancelled = True
        # worker thread will finish and call _on_worker_finished
            
    def _on_worker_finished(self, text, success):
        if not self._is_listening or not self.active_annotation:
            return

        self._is_listening = False
        self._caret_timer.stop()
        old_bbox = self.active_annotation.bbox()

        if success or self._base_text:
            self.active_annotation.text = self._base_text
            refresh_text_bbox(self.active_annotation)
            
            # Remove and re-add for z-order
            self.controller.store.remove(self.active_annotation)
            self.controller.store.add(self.active_annotation)
            self.controller.history.push_add(self.active_annotation)
            
            new_bbox = self.active_annotation.bbox()
            self.controller.refresh(self._combined_bbox(old_bbox, new_bbox))
            log.info("Speech session finished successfully")
        else:
            self.controller.store.remove(self.active_annotation)
            self.controller.refresh(old_bbox)
            log.info("Speech session discarded (no speech)")

        self.active_annotation = None
        self.worker = None

    def cancel_session(self):
        if not self._is_listening:
            return

        self._is_listening = False
        self._caret_timer.stop()
        
        if self.worker:
            self.worker.cancelled = True
            
        if self.active_annotation:
            old_bbox = self.active_annotation.bbox()
            self.controller.store.remove(self.active_annotation)
            self.controller.refresh(old_bbox)
            self.active_annotation = None
            
        self.worker = None
        log.info("Speech session cancelled")

    def _combined_bbox(self, old, new):
        return (
            min(old[0], new[0]) - 4, min(old[1], new[1]) - 4,
            max(old[2], new[2]) + 4, max(old[3], new[3]) + 4,
        )
