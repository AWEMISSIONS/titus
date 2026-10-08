from __future__ import annotations

import platform
import sys
import time

import cv2


def try_camera(index: int):
    results=[]
    for name,backend in [("DirectShow",cv2.CAP_DSHOW),("Media Foundation",cv2.CAP_MSMF),("Default",cv2.CAP_ANY)]:
        cap=None
        try:
            start=time.perf_counter()
            cap=cv2.VideoCapture(index,backend)
            opened=cap.isOpened()
            ok=False
            shape=None
            if opened:
                ok,frame=cap.read()
                if ok and frame is not None:
                    shape=tuple(frame.shape)
            elapsed=(time.perf_counter()-start)*1000
            results.append((name,opened,ok,shape,elapsed))
        except Exception as exc:
            results.append((name,False,False,str(exc),0))
        finally:
            try:
                if cap is not None:
                    cap.release()
            except Exception:
                pass
    return results


def main():
    print("TITUS CAMERA DIAGNOSTICS")
    print("="*60)
    print("Windows:",platform.platform())
    print("Python:",sys.version.replace("\n"," "))
    print("OpenCV:",cv2.__version__)
    print()
    any_found=False
    for idx in range(8):
        rows=try_camera(idx)
        working=[r for r in rows if r[2]]
        if working:
            any_found=True
            print(f"Camera {idx}: WORKING")
            for name,opened,ok,shape,elapsed in rows:
                print(f"  {name:16} opened={opened} frame={ok} shape={shape} start={elapsed:.0f}ms")
        else:
            print(f"Camera {idx}: no usable frame")
    print()
    if any_found:
        print("At least one camera works. Use the matching Camera number inside Titus.")
    else:
        print("No camera returned a frame.")
        print("Close Camera, Zoom, Teams, OBS, browsers, or other apps using the webcam.")
        print("Then check Windows Settings > Privacy & security > Camera and allow desktop apps.")
    input("\nPress Enter to close...")


if __name__=="__main__":
    main()
