# -*- coding: utf-8 -*-
"""PAK Graphic Viewer 클린 캡처 — Ctrl+C(클립보드) 방식.

화면 영역 스크린샷(ImageGrab.grab bbox)이 아니라, PAK 뷰어에서 Ctrl+C로
'그래프 자체'를 클립보드에 복사한 뒤 저장한다. 따라서 위에 다른 창(작업 관리자,
채팅창 등)이 겹쳐 있어도 그래프가 온전하게 저장된다.

사용:
    python pak_capture_clip.py [출력경로]
    (기본 출력: C:/MCPProject_pak/clean.png)

의존성: uiautomation, pillow  (PAK MCP와 동일 환경)
"""
import sys, time

try:
    import uiautomation as auto
    from PIL import ImageGrab
except Exception as e:
    print("의존성 필요: pip install uiautomation pillow  (%s)" % e)
    sys.exit(1)

OUT = sys.argv[1] if len(sys.argv) > 1 else "C:/MCPProject_pak/clean.png"


def find_viewer():
    """PAK 'Graphic Viewer' 최상위 창 찾기 (MCP capture_viewer와 동일 로직)."""
    for w in auto.GetRootControl().GetChildren():
        try:
            if w.ControlTypeName == "WindowControl" and \
               "graphic viewer" in (w.Name or "").lower():
                return w
        except Exception:
            pass
    return None


def main():
    win = find_viewer()
    if not win:
        print("Graphic Viewer 창을 찾지 못했습니다. 그래프를 먼저 출력(Graphic Output)하세요.")
        sys.exit(1)

    # 뷰어를 활성화하고 그래프를 클립보드로 복사 (Ctrl+C)
    try:
        win.SetActive()
        win.SetFocus()
    except Exception:
        pass
    time.sleep(0.5)
    win.SendKeys("{Ctrl}c", waitTime=0.1)
    time.sleep(0.6)

    img = ImageGrab.grabclipboard()
    if img is None or isinstance(img, list):
        print("클립보드에 이미지가 없습니다. 뷰어가 활성 상태인지 확인 후 다시 시도하세요.")
        sys.exit(1)

    img.save(OUT)
    print("SAVED", OUT, img.size)


if __name__ == "__main__":
    main()
