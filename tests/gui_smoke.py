"""Real Qt event-loop + threaded sim:// integration test and visual artifacts.

Run separately: python tests/gui_smoke.py
"""
import os
import argparse
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtGui import QFontDatabase
from main import MainWindow
from tuning.config_dialog import ConfigDialog
from tuning.storage import load_session
from tuning.reporting import export_html, export_csv


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screenshots-dir",type=Path,help="Also save the six current UI previews here")
    args=parser.parse_args()
    artifacts=Path(__file__).resolve().parents[1]/".test-artifacts"
    artifacts.mkdir(exist_ok=True)
    os.environ["NOVA_DATA_DIR"]=str(artifacts)
    app=QApplication.instance() or QApplication([])
    if os.name=="nt" and not QFontDatabase.families():
        for font in ("msyh.ttc","segoeui.ttf","consola.ttf","seguiemj.ttf","seguisym.ttf"):
            QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR","C:/Windows"))/"Fonts"/font))
    errors=[]
    old_hook=sys.excepthook
    sys.excepthook=lambda *args:errors.append(str(args[1]))
    window=MainWindow()
    window.resize(1440,900)
    window.show()
    page=window._ai_page
    try:
        page._demo_profile()
        page._capture_seconds.setValue(2)
        page._max_trials.setValue(4)
        window._serial_page._port_combo.setCurrentText("sim://")
        window._serial_page._toggle_serial()
        assert window._worker.is_open()
        window._switch_page(2)
        page._run_mode.setCurrentIndex(1)
        page._start_automatic(confirmed=True)
        deadline=time.monotonic()+100
        last=None
        while page._auto.active and page._auto.state!="review" and time.monotonic()<deadline:
            QTest.qWait(20)
            if last!=page._auto.state:
                last=page._auto.state
                print("state:",last,page._auto.message,flush=True)
        assert page._auto.state=="review",page._auto.message
        assert not window._worker._port.device.enabled
        page._auto.decide(True)
        for _ in range(100):
            QTest.qWait(20)
            if page._auto.state=="accepted":
                break
        assert page._auto.state=="accepted",page._auto.message
        assert window._worker.owner is None
        assert page._session_path and page._session_path.exists()
        _,config,history=load_session(page._session_path)
        assert len(history)==4
        export_html(artifacts/"demo-report.html",history,config)
        export_csv(artifacts/"demo-data.csv",history)
        for theme in ("light","dark"):
            window._apply_theme(theme,persist=False)
            for index,name in enumerate(("serial","pid","ai")):
                window._switch_page(index)
                QTest.qWait(80)
                window.grab().save(str(artifacts/f"{name}-{theme}.png"))
                if args.screenshots_dir:
                    args.screenshots_dir.mkdir(parents=True,exist_ok=True)
                    assert window.grab().save(str(args.screenshots_dir/f"{name}-{theme}.png"))
        dialog=ConfigDialog(page._config(),window)
        dialog.show()
        QTest.qWait(100)
        dialog.grab().save(str(artifacts/"profile.png"))
        dialog.close()
        # Deliberate disconnect during an automatic trial must await STOP, never reopen.
        page._start_automatic(confirmed=True)
        QTest.qWait(500)
        window._serial_page._toggle_serial()
        for _ in range(150):
            QTest.qWait(20)
            if not window._worker.is_open() and not page._auto.active:
                break
        assert not window._worker.is_open()
        assert not page._auto.active
        QTest.qWait(300)
        assert not window._worker.is_open()
        assert not errors,errors
        print("GUI integration PASS; artifacts:",artifacts,flush=True)
    finally:
        window._worker.close()
        if page._auto:
            page._auto.state="aborted"
        window.close()
        sys.excepthook=old_hook


if __name__=="__main__":
    main()
